import json
from datetime import datetime
from quoting_agent import QuotingAgent
from request_schema import ParsedItems
from smolagents.agents import ToolOutput
from smolagents import OpenAIServerModel
from typing import Literal, TypedDict, Any
from pricing import catalog_unit, convert_quantity, price_quote
from request_understanding_agent import RequestUnderstandingAgent
from inventory_management_agent import InventoryManagementAgent, plan_replenishment
from order_fulfillment_agent import OrderFulfillmentAgent, confirm_order, finalize_order



OrchestratorStatus = Literal[
    'out_of_scope',
    'needs_clarification',
    'contains_unmatched_items',
    'unfulfillable',
    'quoted',
    'fulfilled',
]


class ConversationMessage(TypedDict):
    '''One message in the conversation history.'''
    role: Literal['customer', 'assistant']
    content: str


class OrchestratorResult(TypedDict):
    '''Status, customer reply and parsed request for one message.'''
    status: OrchestratorStatus
    reply: str | None
    parsed: ParsedItems


def run_tool(agent, task: str, tool_name: str) -> Any:
    '''
    Run an agent and return the raw output of its tool call, or None.
    Read the Python tool result directly instead of parsing the agent's
    model-generated final answer.
    '''
    output = None
    for event in agent.run(task, stream=True, reset=True):
        if isinstance(event, ToolOutput) and event.tool_call.name == tool_name:
            output = event.output
    return output


class Orchestrator:
    '''Coordinates the multi-agent system.'''

    def __init__(self, model: OpenAIServerModel, auto_confirm: bool = True) -> None:
        self.request_understanding_agent = RequestUnderstandingAgent(model=model)
        self.inventory_management_agent = InventoryManagementAgent(model=model)
        self.quoting_agent = QuotingAgent(model=model)
        self.order_fulfillment_agent = OrderFulfillmentAgent(model=model)
        # Batch mode accepts feasible quotes automatically. Interactive callers
        # set False and explicitly confirm a quoted order.
        self.auto_confirm = auto_confirm
        self.conversation: list[ConversationMessage] = []
        self.orders: dict[int, dict] = {}
    
    def start_conversation(self) -> None:
        '''Forget previous customer before handling a new one.'''
        self.conversation = []
    
    def process_customer_message(
        self, message: str, request_date: str, request_id: int
        ) -> OrchestratorResult:
        '''
        Handle one customer message; request date is YYYY-MM-DD.
        '''
        # 1. Save the customer's new message.
        self.conversation.append({'role': 'customer', 'content': message})
        # 2. Send the conversation to the parsing worker
        task = (
            f'Request date: {request_date}\n'
            'Customer conversation:\n'
            + json.dumps(self.conversation, ensure_ascii=False)
        )
        raw_result = self.request_understanding_agent.run(task, reset=True)
        # 3. Validate before using the result;
        parsed = (
            ParsedItems.model_validate_json(raw_result)
            if isinstance(raw_result, str)
            else ParsedItems.model_validate(raw_result)
        )
        # Respond according to scope and purchasing state
        scope_reply = (
            "I can help you with purchasing paper and related supplies. "
            "The unrelated part of your request is outside our services."
        )
        prefix = scope_reply + ' ' if parsed.message_scope == 'mixed' else ''

        def respond(status: OrchestratorStatus, reply: str) -> OrchestratorResult:
            '''Save the reply to the conversation and build the result.'''
            self.conversation.append({'role': 'assistant', 'content': reply})
            return {'status': status, 'reply': reply, 'parsed': parsed}
        
        # Handle out-of-scope messages before asking purchasing questions
        if parsed.message_scope == 'out_of_scope':
            reply = (
                "Thank you for your inquiry. I can assist with purchasing "
                "paper and related supplies, but I'm not able to help with this request."
            )
            if parsed.items:
                reply += (
                    " Your existing paper-supply request is still here "
                    "whenever you're ready to continue."
                )
            else:
                reply += " If you need paper supplies, please let me know what you're looking for."
            return respond('out_of_scope', reply)
        # A relevant inquiry may not identify a product yet.
        if not parsed.items:
            reply = "What paper or paper-related supplies would you like to purchase?"
            return respond('needs_clarification', prefix + reply)
        # Do not ask quantities or dates when every product is unavailable.
        if all(item.match_status == 'not_offered' for item in parsed.items):
            reply = (
                "Unfortunately, the requested products aren't in our catalog. "
                "Would you like an alternative from our paper and related supplies?"
            )
            return respond('contains_unmatched_items', prefix + reply)
        questions = [
            item.clarification_question
            for item in parsed.items
            if item.match_status != 'not_offered' and item.clarification_question
        ]
        # Ask about physical units before delegating to inventory.
        for item in parsed.items:
            if item.match_status != 'matched' or item.units is None:
                continue
            name = item.item_name.value
            base_unit = catalog_unit(name, item.category.value)
            normalized = convert_quantity(
                item.units,
                item.quantity_unit,
                base_unit,
                item.package_size,
                item.package_unit
            )
            if normalized is None:
                question = (
                    f'How many {base_unit}s are in each {item.quantity_unit} of {name}?'
                    if base_unit and item.quantity_unit
                    else f'What unit does the quantity for {name} refer to?'
                )
                questions.append(question)
        if parsed.delivery_date_question:
            questions.append(parsed.delivery_date_question)
        # Group outstanding questions and explain why the order is not confirmed.
        if questions:
            reply = "We can't confirm this order yet. " + " ".join(questions)
            return respond('needs_clarification', prefix + reply)

        # 5. Plan, quote and fulfill the catalog items; mention the others.
        matched = parsed.model_copy(update={
            'items': [item for item in parsed.items if item.match_status == 'matched']
        })
        unavailable = [
            item.customer_description
            for item in parsed.items
            if item.match_status == 'not_offered'
        ]
        if unavailable:
            prefix += (
                "These items aren't in our catalog: "
                + '; '.join(unavailable)
                + '. Here is what we can offer for the rest. ' 
            )
        plan = self._plan(matched, request_date)
        if plan is None:
            reply = (
                "Could you confirm the quantity and unit for each item, "
                "including how many sheets or pieces each package contains?"
            )
            return respond('needs_clarification', prefix + reply)
        if not all(row['can_fulfill'] for row in plan):
            return respond('unfulfillable', prefix + self._decline(plan, matched))
        
        quote = price_quote(matched)
        delivery_date = max(row['ship_date'] for row in plan)
        self.orders[request_id] = {
            'plan': plan,
            'quote': quote,
            'delivery_date': delivery_date,
            'financials': None
        }
        quote_text = self.quoting_agent.run(
            'Prepare a customer quote for this request.\n'
            'Structured request:\n' + matched.model_dump_json(),
            reset=True
        )
        if not self.auto_confirm:
            reply = (
                f'{quote_text}\n\nExpected delivery: {delivery_date}. '
                "Please confirm you'd like to place this order."
            )
            return respond('quoted', prefix + reply)
        
        self.confirm(request_id, request_date)
        reply = (
            f'{quote_text}\n\nYour order is confirmed. '
            f'Expected delivery: {delivery_date}.'
        )
        return respond('fulfilled', prefix + reply)
        
    def confirm(self, request_id: int, order_date: str) -> dict:
        '''Record a quoted order; order date is YYYY-MM-DD.'''
        order = self.orders[request_id]
        confirm_order(request_id, order['plan'], order['quote'], order_date)
        # Reuse the stored entry's transaction IDs if the worker has already
        # finalized it. A new confirmation replaces that entry.
        result = run_tool(
            self.order_fulfillment_agent,
            f'Record confirmed order {request_id}.',
            'finalize_order'
        ) or finalize_order(
            request_id=request_id
        )
        if result['status'] == 'recorded' and result['asset_change'] <= 0:
            raise RuntimeError(
                f'Request {request_id}: the sale did not increase total assets.'
            )
        order['financials'] = result
        return result


    def _plan(self, matched: ParsedItems, request_date: str) -> list[dict] | None:
        '''Replenishment plan from the inventory agent's tool call.'''
        as_of_date = datetime.fromisoformat(request_date).strftime('%m/%d/%y')
        plan = run_tool(
            self.inventory_management_agent,
            task=(
                "Plan stock and replenishment for this request.\n"
                f"Request date (MM/DD/YY): {as_of_date}\n"
                "Structured request:\n" + matched.model_dump_json()
            ),
            tool_name='plan_replenishment',
        )
        if plan is not None:
            return plan
        # The tool only reads the database, so a direct call is a safe fallback.
        try:
            return plan_replenishment(parsed=matched.model_dump(), as_of_date=as_of_date)
        except ValueError:
            return None
    
    @staticmethod
    def _decline(plan: list[dict], matched: ParsedItems) -> str:
        '''Customer-facing reason; never mentions cash or other internals.'''
        late = [row for row in plan if row['reject_reason'] == 'late_delivery']
        if late:
            details = '; '.join(
                f"{row['item_name']} (earliest {row['ship_date']})" for row in late
            )
            return (
                f"Unfortunately we can't deliver everything by "
                f"{matched.delivery_by.isoformat()}: {details}. "
                "Would a later delivery date work for you?"
            )
        return (
            "Unfortunately we can't accommodate an order of this size right now. "
            "A smaller quantity may be possible; let us know if you'd like a revised quote."
        )





