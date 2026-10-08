import numpy as np
import pandas as pd
from datetime import datetime
from pricing import catalog_unit, convert_quantity
from smolagents import OpenAIServerModel, ToolCallingAgent, tool
from request_schema import ParsedItems, paper_supplies
from operations import (
    get_all_inventory,
    get_stock_level,
    get_cash_balance,
    get_supplier_delivery_date,
)


@tool
def list_low_stock_items(as_of_date: str) -> list[dict]:
    """
    List catalog items at or below their minimum stock level on a date,
    for inventory overviews and restocking checks. Planning only; no
    transactions are recorded.

    Args:
        as_of_date: Date in YYYY-MM-DD format.
    """
    # get_all_inventory omits items whose stock has reached zero.
    stock = get_all_inventory(as_of_date)
    return [
        {
            "item_name": name,
            "current_stock": int(stock.get(name, 0)),
            "min_stock_level": details["min_stock_level"],
        }
        for name, details in paper_supplies.items()
        if stock.get(name, 0) <= details["min_stock_level"]
    ]


@tool
def plan_replenishment(parsed: dict, as_of_date: str) -> list[dict]:
    """
    Plan stock for a structured request: check current stock and cash,
    decide replenishment quantities, and estimate ship dates against the
    customer's deadline. Planning only; no transactions are recorded.

    Args:
        parsed: Structured request with message_scope, items,
            delivery_by, and delivery_date_question.
        as_of_date: Request date in MM/DD/YY format.
    """
    request = ParsedItems.model_validate(parsed)
    query_date = datetime.strptime(as_of_date, "%m/%d/%y").date().isoformat()
    rows = []

    for line_number, item in enumerate(request.items, start=1):
        if item.match_status != "matched":
            continue
        name = item.item_name.value
        stock_unit = catalog_unit(name, item.category.value)
        requested_units = convert_quantity(
            item.units,
            item.quantity_unit,
            stock_unit,
            item.package_size,
            item.package_unit,
        )
        if requested_units is None or not requested_units.is_integer():
            raise ValueError(
                f"Item {line_number} ({name}): cannot convert "
                f"{item.units} {item.quantity_unit!r} into catalog "
                f"{stock_unit!r} units. Confirm the quantity or explicit "
                "package contents before checking stock."
            )
        rows.append(
            {
                "item_name": name,
                "category": item.category.value,
                "unit_price": item.unit_price,
                "min_stock_level": item.min_stock_level,
                "stock_unit": stock_unit,
                "requested_units": int(requested_units),
            }
        )

    columns = [
        "item_name",
        "category",
        "unit_price",
        "min_stock_level",
        "stock_unit",
        "requested_units",
    ]
    df = pd.DataFrame(rows, columns=columns)

    if df.empty:
        return []

    # Combine repeated product lines after all quantities share the stock unit.
    df = df.groupby(columns[:-1], as_index=False, sort=False, dropna=False)[
        "requested_units"
    ].sum()

    def read_stock(name: str) -> int:
        """Current stock of one item on the query date."""
        stock = get_stock_level(name, query_date)
        if len(stock) != 1 or pd.isna(stock["current_stock"].iloc[0]):
            raise ValueError(
                f"{name}: expected one non-null stock value on {query_date}."
            )
        return int(stock["current_stock"].iloc[0])

    df["current_stock"] = df["item_name"].apply(read_stock)
    df["surplus"] = df["current_stock"] - df["requested_units"]
    df["need_met"] = df["surplus"] >= 0
    # Reorder when this order leaves stock below min_stock_level.
    # Keep the order small when the customer waits for it; otherwise refill to 3x.
    target = np.where(df["need_met"], 3 * df["min_stock_level"], df["min_stock_level"])
    df["replenishment_units"] = np.where(
        df["surplus"] < df["min_stock_level"], target - df["surplus"], 0
    )
    cash_balance = get_cash_balance(query_date)
    df["shortfall_units"] = (-df["surplus"]).clip(lower=0)
    df["buffer_units"] = df["replenishment_units"] - df["shortfall_units"]
    required = (df["shortfall_units"] * df["unit_price"]).sum()
    buffer = (df["buffer_units"] * df["unit_price"]).sum()
    enough_cash = required <= cash_balance
    # Buy the buffer only when cash also covers it.
    buy_buffer = required + buffer <= cash_balance
    df["ordered_units"] = df["shortfall_units"] + (
        df["buffer_units"] if buy_buffer else 0
    )

    # Stock on hand ships on the request date; a shortfall waits for its stock order.
    df["ship_date"] = [
        (
            query_date
            if row.need_met
            # The customer waits only for the shortfall; the restock to
            # min_stock_level is a separate order that doesn't hold them up.
            else get_supplier_delivery_date(query_date, int(row.shortfall_units))
        )
        for row in df.itertuples()
    ]
    deadline = request.delivery_by.isoformat() if request.delivery_by else None
    df["on_time"] = [deadline is None or day <= deadline for day in df["ship_date"]]

    # Take the order only if cash covers the shortfall and every item arrives in time.
    df["can_fulfill"] = enough_cash and df["on_time"].all()
    if not df["can_fulfill"].all():
        df["ordered_units"] = 0
    # object dtype keeps None; pandas 3 would turn it into NaN in a string column.
    if not enough_cash:
        reasons = ["insufficient_cash"] * len(df)
    else:
        reasons = [None if on_time else "late_delivery" for on_time in df["on_time"]]
    df["reject_reason"] = pd.Series(reasons, index=df.index, dtype=object)

    fields = [
        "item_name",
        "unit_price",
        "requested_units",
        "current_stock",
        "ordered_units",
        "ship_date",
        "on_time",
        "can_fulfill",
        "reject_reason",
    ]
    return df[fields].to_dict("records")


class InventoryManagementAgent(ToolCallingAgent):

    """Worker agent that checks stock, cash and supplier lead times."""
    def __init__(self, model: OpenAIServerModel) -> None:
        super().__init__(
            tools=[plan_replenishment, list_low_stock_items],
            model=model,
            name="inventory_management_agent",
            description=(
                "Checks stock, cash, and supplier lead times for a structured "
                "request and returns a replenishment plan with ship dates."
            ),
            instructions=(
                "You plan inventory for a paper-supply company.\n"
                "- Call plan_replenishment once with the structured request "
                "and the request date exactly as given in the task.\n"
                "- When the task asks for an inventory overview or a "
                "low-stock check instead of a customer request, call "
                "list_low_stock_items with the given date.\n"
                "- The tool is the only source of stock levels, order "
                "quantities, ship dates, and feasibility. Never calculate, "
                "estimate, or change these values yourself.\n"
                "- The plan covers only matched catalog items; say so if the "
                "request contains other items.\n"
                "- If the tool reports that a quantity cannot be converted, "
                "report which item needs its quantity or package contents "
                "confirmed. Do not guess package sizes.\n"
                "- This is planning only: do not record transactions, "
                "promise delivery, or write to the customer.\n"
                "- Return the tool result unchanged as a JSON list as your "
                "final answer, with no commentary."
            ),
        )
