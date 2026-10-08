"""Catalog, SQLite operations, and the batch customer-request runner."""

import pandas as pd
import numpy as np
import time
from collections import Counter
from sqlalchemy.sql import text
from datetime import datetime, timedelta
from typing import Dict, List, Union
from sqlalchemy import create_engine, Engine

db_engine = create_engine("sqlite:///munder_difflin.db")

# Catalog prices represent the cost of one inventory unit.
paper_supplies = [
    # Paper Types (priced per sheet unless specified)
    {"item_name": "A4 paper", "category": "paper", "unit_price": 0.05},
    {"item_name": "Letter-sized paper", "category": "paper", "unit_price": 0.06},
    {"item_name": "Cardstock", "category": "paper", "unit_price": 0.15},
    {"item_name": "Colored paper", "category": "paper", "unit_price": 0.10},
    {"item_name": "Glossy paper", "category": "paper", "unit_price": 0.20},
    {"item_name": "Matte paper", "category": "paper", "unit_price": 0.18},
    {"item_name": "Recycled paper", "category": "paper", "unit_price": 0.08},
    {"item_name": "Eco-friendly paper", "category": "paper", "unit_price": 0.12},
    {"item_name": "Poster paper", "category": "paper", "unit_price": 0.25},
    {"item_name": "Banner paper", "category": "paper", "unit_price": 0.30},
    {"item_name": "Kraft paper", "category": "paper", "unit_price": 0.10},
    {"item_name": "Construction paper", "category": "paper", "unit_price": 0.07},
    {"item_name": "Wrapping paper", "category": "paper", "unit_price": 0.15},
    {"item_name": "Glitter paper", "category": "paper", "unit_price": 0.22},
    {"item_name": "Decorative paper", "category": "paper", "unit_price": 0.18},
    {"item_name": "Letterhead paper", "category": "paper", "unit_price": 0.12},
    {"item_name": "Legal-size paper", "category": "paper", "unit_price": 0.08},
    {"item_name": "Crepe paper", "category": "paper", "unit_price": 0.05},
    {"item_name": "Photo paper", "category": "paper", "unit_price": 0.25},
    {"item_name": "Uncoated paper", "category": "paper", "unit_price": 0.06},
    {"item_name": "Butcher paper", "category": "paper", "unit_price": 0.10},
    {"item_name": "Heavyweight paper", "category": "paper", "unit_price": 0.20},
    {"item_name": "Standard copy paper", "category": "paper", "unit_price": 0.04},
    {"item_name": "Bright-colored paper", "category": "paper", "unit_price": 0.12},
    {"item_name": "Patterned paper", "category": "paper", "unit_price": 0.15},
    # Product Types (priced per unit)
    {
        "item_name": "Paper plates",
        "category": "product",
        "unit_price": 0.10,
    },  # per plate
    {"item_name": "Paper cups", "category": "product", "unit_price": 0.08},  # per cup
    {
        "item_name": "Paper napkins",
        "category": "product",
        "unit_price": 0.02,
    },  # per napkin
    {
        "item_name": "Disposable cups",
        "category": "product",
        "unit_price": 0.10,
    },  # per cup
    {
        "item_name": "Table covers",
        "category": "product",
        "unit_price": 1.50,
    },  # per cover
    {
        "item_name": "Envelopes",
        "category": "product",
        "unit_price": 0.05,
    },  # per envelope
    {
        "item_name": "Sticky notes",
        "category": "product",
        "unit_price": 0.03,
    },  # per sheet
    {"item_name": "Notepads", "category": "product", "unit_price": 2.00},  # per pad
    {
        "item_name": "Invitation cards",
        "category": "product",
        "unit_price": 0.50,
    },  # per card
    {"item_name": "Flyers", "category": "product", "unit_price": 0.15},  # per flyer
    {
        "item_name": "Party streamers",
        "category": "product",
        "unit_price": 0.05,
    },  # per roll
    {
        "item_name": "Decorative adhesive tape (washi tape)",
        "category": "product",
        "unit_price": 0.20,
    },  # per roll
    {
        "item_name": "Paper party bags",
        "category": "product",
        "unit_price": 0.25,
    },  # per bag
    {
        "item_name": "Name tags with lanyards",
        "category": "product",
        "unit_price": 0.75,
    },  # per tag
    {
        "item_name": "Presentation folders",
        "category": "product",
        "unit_price": 0.50,
    },  # per folder
    # Large-format items (priced per unit)
    {
        "item_name": "Large poster paper (24x36 inches)",
        "category": "large_format",
        "unit_price": 1.00,
    },
    {
        "item_name": "Rolls of banner paper (36-inch width)",
        "category": "large_format",
        "unit_price": 2.50,
    },
    # Specialty papers
    {"item_name": "100 lb cover stock", "category": "specialty", "unit_price": 0.50},
    {"item_name": "80 lb text paper", "category": "specialty", "unit_price": 0.40},
    {"item_name": "250 gsm cardstock", "category": "specialty", "unit_price": 0.30},
    {"item_name": "220 gsm poster paper", "category": "specialty", "unit_price": 0.35},
]

def generate_sample_inventory(
    paper_supplies: list, coverage: float = 1.0, seed: int = 137
) -> pd.DataFrame:
    """Generate reproducible simulated inventory for a fraction of the catalog.

    Args:
        paper_supplies: Catalog records with item_name, category, and unit_price.
        coverage: Fraction selected without replacement, rounded down; default 1.0.
        seed: Random seed for item selection and stock levels; default 137.

    Returns:
        DataFrame with catalog fields, current_stock (200–799 inventory units),
        and min_stock_level (50–149 inventory units).
    """
    # Keep item selection and stock levels reproducible.
    np.random.seed(seed)

    num_items = int(len(paper_supplies) * coverage)

    selected_indices = np.random.choice(
        range(len(paper_supplies)), size=num_items, replace=False
    )

    selected_items = [paper_supplies[i] for i in selected_indices]

    inventory = []
    for item in selected_items:
        inventory.append(
            {
                "item_name": item["item_name"],
                "category": item["category"],
                "unit_price": item["unit_price"],
                "current_stock": np.random.randint(200, 800),
                "min_stock_level": np.random.randint(
                    50, 150
                ),
            }
        )

    return pd.DataFrame(inventory)


def init_database(db_engine: Engine, seed: int = 137) -> Engine:
    """Reset local tables and seed the catalog, simulated inventory, and ledger.

    Loads quote_requests.csv and quotes.csv from the working directory. Replaces
    transactions, quote_requests, quotes, inventory, and paper_supplies, then seeds
    every catalog item and a $50,000 opening cash entry dated January 1, 2025.

    Args:
        db_engine: SQLAlchemy engine for the database to reset.
        seed: Random seed for inventory generation; default 137.

    Returns:
        The supplied engine. Setup errors are logged and raised.
    """
    try:
        transactions_schema = pd.DataFrame(
            {
                "id": [],
                "item_name": [],
                "transaction_type": [],  # 'stock_orders' or 'sales'
                "units": [],  # Quantity involved
                "price": [],  # Total price for the transaction
                "transaction_date": [],  # ISO-formatted date
            }
        )
        transactions_schema.to_sql(
            "transactions", db_engine, if_exists="replace", index=False
        )

        initial_date = datetime(2025, 1, 1).isoformat()

        quote_requests_df = pd.read_csv("quote_requests.csv")
        quote_requests_df["id"] = range(1, len(quote_requests_df) + 1)
        quote_requests_df.to_sql(
            "quote_requests", db_engine, if_exists="replace", index=False
        )

        quotes_df = pd.read_csv("quotes.csv")
        quotes_df["request_id"] = range(1, len(quotes_df) + 1)
        quotes_df["order_date"] = initial_date

        quotes_df = quotes_df[
            [
                "request_id",
                "total_amount",
                "quote_explanation",
                "order_date",
            ]
        ]
        quotes_df.to_sql("quotes", db_engine, if_exists="replace", index=False)

        inventory_df = generate_sample_inventory(paper_supplies, seed=seed)

        initial_transactions = []

        # A ledger entry without an item supplies the opening cash balance.
        initial_transactions.append(
            {
                "item_name": None,
                "transaction_type": "sales",
                "units": None,
                "price": 50000.0,
                "transaction_date": initial_date,
            }
        )

        for _, item in inventory_df.iterrows():
            initial_transactions.append(
                {
                    "item_name": item["item_name"],
                    "transaction_type": "stock_orders",
                    "units": item["current_stock"],
                    "price": item["current_stock"] * item["unit_price"],
                    "transaction_date": initial_date,
                }
            )

        pd.DataFrame(initial_transactions).to_sql(
            "transactions", db_engine, if_exists="append", index=False
        )

        inventory_df.to_sql("inventory", db_engine, if_exists="replace", index=False)

        # Snapshot the catalog as created: every item (coverage=1.0) with its
        # category, unit price and minimum stock level. request_schema reads it.
        inventory_df[
            ["item_name", "category", "unit_price", "min_stock_level"]
        ].to_sql("paper_supplies", db_engine, if_exists="replace", index=False)

        return db_engine

    except Exception as e:
        print(f"Error initializing database: {e}")
        raise


def create_transaction(
    item_name: str,
    transaction_type: str,
    quantity: int,
    price: float,
    date: Union[str, datetime],
) -> int:
    """Append a stock purchase or sale to the transaction ledger.

    Args:
        item_name: Catalog product name.
        transaction_type: Either stock_orders or sales.
        quantity: Number of inventory units.
        price: Total transaction amount, not a per-unit price.
        date: ISO 8601 string or datetime.

    Returns:
        The inserted transaction ID.

    Raises:
        ValueError: Unsupported transaction_type. Errors are logged and raised.
    """
    try:
        date_str = date.isoformat() if isinstance(date, datetime) else date

        if transaction_type not in {"stock_orders", "sales"}:
            raise ValueError("Transaction type must be 'stock_orders' or 'sales'")

        transaction = pd.DataFrame(
            [
                {
                    "item_name": item_name,
                    "transaction_type": transaction_type,
                    "units": quantity,
                    "price": price,
                    "transaction_date": date_str,
                }
            ]
        )

        transaction.to_sql("transactions", db_engine, if_exists="append", index=False)

        result = pd.read_sql("SELECT last_insert_rowid() as id", db_engine)
        return int(result.iloc[0]["id"])

    except Exception as e:
        print(f"Error creating transaction: {e}")
        raise


def get_all_inventory(as_of_date: str) -> Dict[str, int]:
    """Return positive stock balances from purchases minus sales.

    Args:
        as_of_date: Inclusive cutoff in YYYY-MM-DD format.

    Returns:
        Product names mapped to remaining inventory units; zero stock is omitted.
    """
    query = """
        SELECT
            item_name,
            SUM(CASE
                WHEN transaction_type = 'stock_orders' THEN units
                WHEN transaction_type = 'sales' THEN -units
                ELSE 0
            END) as stock
        FROM transactions
        WHERE item_name IS NOT NULL
        AND transaction_date <= :as_of_date
        GROUP BY item_name
        HAVING stock > 0
    """

    result = pd.read_sql(query, db_engine, params={"as_of_date": as_of_date})

    return dict(zip(result["item_name"], result["stock"]))


def get_stock_level(item_name: str, as_of_date: Union[str, datetime]) -> pd.DataFrame:
    """Return one product's purchases minus sales through an inclusive cutoff.

    Args:
        item_name: Catalog product name.
        as_of_date: ISO date string or datetime.

    Returns:
        Single-row DataFrame with item_name and current_stock in inventory units.
        current_stock is zero when no matching transactions exist.
    """
    if isinstance(as_of_date, datetime):
        as_of_date = as_of_date.isoformat()

    stock_query = """
        SELECT
            item_name,
            COALESCE(SUM(CASE
                WHEN transaction_type = 'stock_orders' THEN units
                WHEN transaction_type = 'sales' THEN -units
                ELSE 0
            END), 0) AS current_stock
        FROM transactions
        WHERE item_name = :item_name
        AND transaction_date <= :as_of_date
    """

    return pd.read_sql(
        stock_query,
        db_engine,
        params={"item_name": item_name, "as_of_date": as_of_date},
    )


def get_supplier_delivery_date(input_date_str: str, quantity: int) -> str:
    """Estimate delivery using quantity-based supplier lead times.

    Lead times are 0 days for up to 10 units, 1 day for 11–100 units,
    4 days for 101–1,000 units, and 7 days for larger orders.

    Args:
        input_date_str: Starting date in YYYY-MM-DD format; time suffix ignored.
            Invalid dates are logged and fall back to the current local date.
        quantity: Number of inventory units ordered.

    Returns:
        Estimated delivery date in YYYY-MM-DD format.
    """
    print(
        f"FUNC (get_supplier_delivery_date): Calculating for qty {quantity} from date string '{input_date_str}'"
    )

    try:
        input_date_dt = datetime.fromisoformat(input_date_str.split("T")[0])
    except (ValueError, TypeError):
        print(
            f"WARN (get_supplier_delivery_date): Invalid date format '{input_date_str}', using today as base."
        )
        input_date_dt = datetime.now()

    if quantity <= 10:
        days = 0
    elif quantity <= 100:
        days = 1
    elif quantity <= 1000:
        days = 4
    else:
        days = 7

    delivery_date_dt = input_date_dt + timedelta(days=days)

    return delivery_date_dt.strftime("%Y-%m-%d")


def get_cash_balance(as_of_date: Union[str, datetime]) -> float:
    """Return sales amounts minus stock purchase costs through a cutoff date.

    Args:
        as_of_date: Inclusive cutoff as an ISO date string or datetime.

    Returns:
        Cash balance; 0.0 for an empty ledger or a logged query error.
    """
    try:
        if isinstance(as_of_date, datetime):
            as_of_date = as_of_date.isoformat()

        transactions = pd.read_sql(
            "SELECT * FROM transactions WHERE transaction_date <= :as_of_date",
            db_engine,
            params={"as_of_date": as_of_date},
        )

        if not transactions.empty:
            total_sales = transactions.loc[
                transactions["transaction_type"] == "sales", "price"
            ].sum()
            total_purchases = transactions.loc[
                transactions["transaction_type"] == "stock_orders", "price"
            ].sum()
            return float(total_sales - total_purchases)

        return 0.0

    except Exception as e:
        print(f"Error getting cash balance: {e}")
        return 0.0


def generate_financial_report(as_of_date: Union[str, datetime]) -> Dict:
    """Report cash, inventory at catalog cost, and sales through a cutoff date.

    Args:
        as_of_date: Inclusive cutoff as an ISO date string or datetime.

    Returns:
        Dictionary with as_of_date, cash_balance, inventory_value, total_assets
        (cash plus inventory), inventory_summary, and top_selling_products
        (up to five ledger entries grouped by item and ranked by sales revenue).
    """
    if isinstance(as_of_date, datetime):
        as_of_date = as_of_date.isoformat()

    cash = get_cash_balance(as_of_date)

    inventory_df = pd.read_sql("SELECT * FROM inventory", db_engine)
    inventory_value = 0.0
    inventory_summary = []

    for _, item in inventory_df.iterrows():
        stock_info = get_stock_level(item["item_name"], as_of_date)
        stock = stock_info["current_stock"].iloc[0]
        item_value = stock * item["unit_price"]
        inventory_value += item_value

        inventory_summary.append(
            {
                "item_name": item["item_name"],
                "stock": stock,
                "unit_price": item["unit_price"],
                "value": item_value,
            }
        )

    top_sales_query = """
        SELECT item_name, SUM(units) as total_units, SUM(price) as total_revenue
        FROM transactions
        WHERE transaction_type = 'sales' AND transaction_date <= :date
        GROUP BY item_name
        ORDER BY total_revenue DESC
        LIMIT 5
    """
    top_sales = pd.read_sql(top_sales_query, db_engine, params={"date": as_of_date})
    top_selling_products = top_sales.to_dict(orient="records")

    return {
        "as_of_date": as_of_date,
        "cash_balance": cash,
        "inventory_value": inventory_value,
        "total_assets": cash + inventory_value,
        "inventory_summary": inventory_summary,
        "top_selling_products": top_selling_products,
    }


def search_quote_history(search_terms: List[str], limit: int = 5) -> List[Dict]:
    """Find historical quotes matching every term in request or explanation text.

    Matches are case-insensitive substrings. Empty search_terms applies no filter.

    Args:
        search_terms: Each term must appear in either source text field.
        limit: Maximum records to return; default 5.

    Returns:
        Records ordered by descending order_date, with original_request,
        total_amount, quote_explanation, and order_date.
    """
    conditions = []
    params = {}

    for i, term in enumerate(search_terms):
        param_name = f"term_{i}"
        conditions.append(
            f"(LOWER(qr.response) LIKE :{param_name} OR "
            f"LOWER(q.quote_explanation) LIKE :{param_name})"
        )
        params[param_name] = f"%{term.lower()}%"

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
        SELECT
            qr.response AS original_request,
            q.total_amount,
            q.quote_explanation,
            q.order_date
        FROM quotes q
        JOIN quote_requests qr ON q.request_id = qr.id
        WHERE {where_clause}
        ORDER BY q.order_date DESC
        LIMIT {limit}
    """

    with db_engine.connect() as conn:
        result = conn.execute(text(query), params)
        return [dict(row._mapping) for row in result]


def run_scenarios():
    """Reset the database and process simulated requests in date order.

    Reads quote_requests_sample.csv from the working directory, writes
    test_results.csv, and returns the outcome records. Input dates use MM/DD/YY;
    output dates use YYYY-MM-DD. Request errors are logged without ending the
    batch. A failure to load the input returns None.
    """
    print("Initializing Database...")
    init_database(db_engine)
    try:
        quote_requests_sample = pd.read_csv("quote_requests_sample.csv")
        quote_requests_sample["request_date"] = pd.to_datetime(
            quote_requests_sample["request_date"], format="%m/%d/%y", errors="coerce"
        )
        quote_requests_sample.dropna(subset=["request_date"], inplace=True)
        quote_requests_sample = quote_requests_sample.sort_values("request_date")
    except Exception as e:
        print(f"FATAL: Error loading test data: {e}")
        return

    # Imported here: the agent modules import this file, and request_schema
    # reads the catalog table that init_database has just created.
    from model_config import create_model
    from orchestrator import Orchestrator

    orchestrator = Orchestrator(model=create_model())

    results = []
    for idx, row in quote_requests_sample.iterrows():
        request_date = row["request_date"].strftime("%Y-%m-%d")

        print(f"\n=== Request {idx+1} ===")
        print(f"Request Date: {request_date}")
        print(f"Customer request: {row['request']}")

        request_with_date = f"{row['request']} (Date of request: {request_date})"

        # Every sample request comes from a different customer.
        orchestrator.start_conversation()
        try:
            result = orchestrator.process_customer_message(
                request_with_date, request_date, request_id=idx + 1
            )
            status, response = result["status"], result["reply"]
        except Exception as e:
            # Keep the run going; the customer never sees internal errors.
            print(f"ERROR handling request {idx+1}: {type(e).__name__}: {e}")
            status = "error"
            response = (
                "We're sorry, we couldn't process your request right now. "
                "Please contact us again shortly."
            )

        report = generate_financial_report(request_date)
        current_cash = report["cash_balance"]
        current_inventory = report["inventory_value"]

        print(f"Status: {status}")
        print(f"Response: {response}")

        results.append(
            {
                "request_id": idx + 1,
                "request_date": request_date,
                "status": status,
                "cash_balance": current_cash,
                "inventory_value": current_inventory,
                "response": response,
            }
        )

        time.sleep(1)

    pd.DataFrame(results).to_csv("test_results.csv", index=False)
    print(f"\nProcessed {len(results)} requests:")
    for status, count in Counter(result["status"] for result in results).items():
        print(f"  {status}: {count}")
    print("Detailed results saved to test_results.csv")
    return results


if __name__ == "__main__":
    results = run_scenarios()
