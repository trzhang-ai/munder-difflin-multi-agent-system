from pricing import Quote
from operations import create_transaction, generate_financial_report
from smolagents import ToolCallingAgent, OpenAIServerModel, tool


# Filled by the orchestrator once the customer accepts a quote. finalize_order
# reads amounts from here, so the model never supplies quantities or prices.
confirmed_orders: dict[int, dict] = {}

def confirm_order(
        request_id: int,
        plan: list[dict],
        quote: Quote,
        order_date: str,
) -> None:
    '''Store an accepted order for finalize_order; order_date is YYYY-MM-DD.'''
    if not plan or not all(row['can_fulfill'] for row in plan):
        raise ValueError(f"Request {request_id} cannot be fulfilled.")
    if quote.unpriced:
        raise ValueError(f"Request {request_id} still has unpriced items.")
    confirmed_orders[request_id] = {
        'plan': plan,
        'quote': quote,
        'order_date': order_date,
        'transaction_ids': None,
    }

@tool
def finalize_order(request_id: int) -> dict:
    '''
    Record stock orders and sales, then report cash and total asset changes.
    Quantities, prices and the date come from the stored order. Repeat calls
    against the same stored entry reuse its recorded transaction IDs.

    Args:
        request_id: Identifier of the confirmed order given in the task.
    '''
    order = confirmed_orders.get(request_id)
    if order is None:
        raise ValueError(f"No confirmed order for request {request_id}.")
    if order['transaction_ids'] is not None:
        return {'status': 'already_recorded', 'transaction_ids': order['transaction_ids']}
    date = order['order_date']
    # Prepare entries before writing; database writes are separate transactions.
    entries = [
        (row['item_name'], 'stock_orders', int(row['ordered_units']),
         round(row['ordered_units'] * row['unit_price'], 2))
        for row in order['plan'] if row['ordered_units'] > 0
    ] + [
        (line.item_name, 'sales', line.quantity, line.sale_price)
        for line in order['quote'].lines
    ]
    before = generate_financial_report(date)
    # Stock first, so a sale never takes the stock level below zero.
    ids = [create_transaction(*entry, date) for entry in entries]
    after = generate_financial_report(date)
    order['transaction_ids'] = ids
    return {
        'status': 'recorded',
        'transaction_ids': ids,
        'cash_change': float(round(after['cash_balance'] - before['cash_balance'], 2)),
        'asset_change': float(round(after['total_assets'] - before['total_assets'], 2))
    }


class OrderFulfillmentAgent(ToolCallingAgent):
    
    '''Worker agent that records confirmed orders.'''
    def __init__(self, model: OpenAIServerModel) -> None:
        super().__init__(
            tools=[finalize_order],
            model=model,
            name='order_fulfillment_agent',
            description=(
                "Records stock orders and sales for a confirmed, priced order "
                "and verifies the resulting cash and asset changes."
            ),
            instructions=(
                "You record confirmed orders for a paper-supply company.\n"
                "- Call finalize_order once with the request_id given in the task.\n"
                "- Never supply, calculate, or change quantities, prices, or "
                "dates; the tool reads them from the confirmed order.\n"
                "- Only use a request_id given in the task. If the tool reports "
                "an error, return the error message; do not retry with other values.\n"
                "- Return the tool result unchanged as JSON as your final answer. "
                "It is internal: never write to the customer."
            ),
        )
