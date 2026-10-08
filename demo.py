"""Preview saved outcomes or request one live quote against simulated stock."""

import argparse
import csv
import io
import os
import sys
from collections import Counter
from contextlib import chdir, redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = PROJECT_DIR / "munder_difflin.db"
CASES = {"quote": 10, "clarification": 3, "deadline": 13}
DEFAULT_REQUEST = (
    "I would like to order 100 sheets of A4 paper, "
    "delivered by April 15, 2025."
)


class DemoError(Exception):
    """An actionable error suitable for the command-line preview."""


def iso_date(value: str) -> str:
    """Accept calendar dates written exactly as YYYY-MM-DD."""
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("use a valid date in YYYY-MM-DD format") from None
    return value


def show_request(request: str, request_date: str, status: str, response: str) -> None:
    print(f"Request date: {request_date}")
    print(f"Status: {status.replace('_', ' ')}")
    print("\nCustomer request:")
    print(request.replace("\\n", "\n"))
    print("\nReply to customer:")
    print(response.replace("\\n", "\n"))


def load_saved_cases(case: str) -> tuple[dict, dict, Counter]:
    """Join the selected result to its original input by request ID."""
    try:
        with (PROJECT_DIR / "test_results.csv").open(encoding="utf-8", newline="") as file:
            results = list(csv.DictReader(file))
        with (PROJECT_DIR / "quote_requests_sample.csv").open(
            encoding="utf-8", newline=""
        ) as file:
            requests = list(csv.DictReader(file))
        selected = next(row for row in results if int(row["request_id"]) == CASES[case])
        request = requests[int(selected["request_id"]) - 1]
        for field in ("request_date", "status", "response"):
            selected[field]
        request["request"]
        counts = Counter({"fulfilled": 0, "unfulfillable": 0, "needs_clarification": 0})
        counts.update(row["status"] for row in results)
    except (OSError, UnicodeError, csv.Error, KeyError, ValueError, IndexError, StopIteration):
        raise DemoError(
            "Saved results could not be read. Restore test_results.csv and "
            "quote_requests_sample.csv in the project directory."
        ) from None
    return request, selected, counts


def run_live_quote(request: str, request_date: str) -> dict:
    """Create a quote without recording a sale; initialize only a missing database."""
    stage = "dependencies"
    try:
        with chdir(PROJECT_DIR), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            from dotenv import load_dotenv

            load_dotenv(PROJECT_DIR / ".env")
            if not os.getenv("OPENAI_API_KEY", "").strip():
                raise DemoError(
                    "Live mode needs OPENAI_API_KEY. Set it in the environment "
                    "or the project's .env file, then try again."
                )

            from operations import db_engine, init_database

            stage = "setup"
            if not DATABASE_PATH.exists():
                init_database(db_engine)

            # The schema loads the catalog at import time, after initialization.
            from model_config import create_model
            from orchestrator import Orchestrator

            stage = "quote"
            orchestrator = Orchestrator(model=create_model(), auto_confirm=False)
            return orchestrator.process_customer_message(request, request_date, request_id=1)
    except DemoError:
        raise
    except ImportError:
        raise DemoError(
            "Live mode needs the project dependencies. Run uv sync --locked in the "
            "project directory, then use uv run python demo.py --live."
        ) from None
    except Exception:
        if stage == "setup":
            message = (
                "The local database could not be loaded. Restore a compatible "
                "munder_difflin.db, or move it aside to initialize a new simulation."
            )
        else:
            message = (
                "The live quote could not be completed. Check OPENAI_API_KEY, "
                "OPENAI_BASE_URL, and OPENAI_MODEL, then try again."
            )
        raise DemoError(message) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, help="saved case to show (default: quote)")
    parser.add_argument("--live", action="store_true", help="request one live quote; no sale recorded")
    parser.add_argument("--request", help="customer request for live mode")
    parser.add_argument("--date", type=iso_date, help="live request date in YYYY-MM-DD format")
    args = parser.parse_args(argv)
    if not args.live and (args.request is not None or args.date is not None):
        parser.error("--request and --date require --live")
    if args.live and args.case is not None:
        parser.error("--case is available for saved previews")
    if args.request is not None and not args.request.strip():
        parser.error("--request must contain a customer message")

    try:
        if args.live:
            request = args.request or DEFAULT_REQUEST
            request_date = args.date or "2025-04-01"
            print("Processing request with the configured model...", flush=True)
            result = run_live_quote(request, request_date)
            print("Live quote — simulated inventory, no sale recorded")
            show_request(request, request_date, result["status"], result["reply"] or "")
        else:
            request, result, counts = load_saved_cases(args.case or "quote")
            print("Saved result preview — no model calls")
            outcomes = ", ".join(
                f"{count} {status.replace('_', ' ')}"
                for status, count in counts.items() if count
            )
            print(f"Saved simulated run: {sum(counts.values())} requests — {outcomes}.")
            show_request(
                request["request"], result["request_date"], result["status"], result["response"]
            )
    except DemoError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
