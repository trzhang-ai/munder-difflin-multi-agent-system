# Munder Difflin Multi-Agent System: Reflection Report

Files: `agent_workflow_diagram.png` (source: `agent_workflow_diagram.mmd`), `test_results.csv`.

## 1. Architecture and the workflow diagram

The system has five agents, the maximum allowed: one orchestrator and four workers. All workers are smolagents `ToolCallingAgent`s that share one model configured in `model_config.py`.

| Agent | Responsibility | Tools (starter helpers used) |
|---|---|---|
| Orchestrator (`orchestrator.py`) | Receives each customer message, decides the next step, delegates to the workers, keeps per-request state, and writes the customer reply. | None; it calls the workers. |
| RequestUnderstandingAgent | Turns free text into a validated `ParsedItems` object: scope (in scope, out of scope, mixed), catalog items, quantities and units, and the delivery deadline. | None (language task only). |
| InventoryManagementAgent | Decides whether the order can be fulfilled: stock, reorder quantities, cash, and ship dates against the deadline. | `plan_replenishment` (`get_stock_level`, `get_cash_balance`, `get_supplier_delivery_date`); `list_low_stock_items` (`get_all_inventory`). |
| QuotingAgent | Prices the order and writes the customer-facing quote. | `calculate_quote` (pricing policy in `pricing.py`); `find_similar_quotes` (`search_quote_history`). |
| OrderFulfillmentAgent | Records a confirmed order and reports its financial effect. | `finalize_order` (`create_transaction`, `generate_financial_report`). |

Each worker owns one stage, so responsibilities do not overlap. Only the inventory agent reads stock levels, only the quoting agent sets prices, and only the fulfillment agent writes transactions.

The orchestrator follows six steps, which match the boxes in the diagram:

1. **Understand the request.** The conversation and request date go to RequestUnderstandingAgent.
2. **Triage.** Out-of-scope messages, missing details, and requests with no catalog items get an immediate reply. All open questions are asked in one reply, because each evaluation request is a single message with no follow-up turn.
3. **Plan stock.** Matched items go to InventoryManagementAgent, which returns per item: current stock, units to order, ship date, whether it is on time, and the reason if it is not.
4. **Check feasibility.** If any item would arrive after the deadline, or the business cannot pay for the shortfall, the order is declined with a customer-safe reason.
5. **Quote.** QuotingAgent prices the order and looks up similar past quotes.
6. **Confirm and record.** The plan and quote are stored, then OrderFulfillmentAgent records the stock orders and sales.

### Why this architecture

- **Language goes to the model; numbers stay in code.** The model handles parsing and writing. Quantities, prices, dates, and transactions come from deterministic functions. The orchestrator reads each tool's exact return value from the agent's run (`run_tool` in `orchestrator.py`) instead of trusting the model's retelling, so no number passes through generated text.
- **A rule-based orchestrator.** The workflow is a fixed sequence of decisions with clear rules, so the orchestrator is ordinary Python. This makes every run reproducible and easy to audit, and it keeps the model from skipping a check or recording a sale twice.
- **The pricing policy follows the starter's accounting.** The starter buys stock and values inventory at the catalog `unit_price`, so `unit_price` is the cost basis. Quotes are cost × 1.25, with a bulk discount of 5% from $500 and 10% from $2,000; the worst case is still 12.5% above cost. The historical quotes in `quotes.csv` are inconsistent: five are failed records with a total of −1, and a rough check found the total stated in the text disagreed with `total_amount` in about a quarter of them. The system therefore uses them only as precedent for wording and discount practice, with their dollar amounts masked.
- **The replenishment policy protects delivery times.**
  - A reorder is placed when an order would leave stock below `min_stock_level`.
  - If the customer is waiting on the shortfall, the plan orders the shortfall plus enough to return to the minimum. The ship date is computed from the shortfall alone, because the restock is a separate supplier order.
  - If stock covers the order, the plan refills to three times the minimum, so the next customer is more likely to be served from stock.
  - The buffer is bought only if cash also covers it.
- **Recording is safe to repeat.** `finalize_order` takes only a request id and reads quantities and prices from the confirmed order. It writes stock orders before sales and records an order only once. If the sale did not increase total assets, the orchestrator raises an error.

## 2. Evaluation results (`test_results.csv`)

All 20 requests in `quote_requests_sample.csv` were processed in date order, with no runtime errors.

| Outcome | Requests |
|---|---|
| Fulfilled | 12 (requests 1, 2, 4–12, 20) |
| Declined: deadline cannot be met | 7 (requests 13–19) |
| Clarification needed | 1 (request 3) |

- **Cash** changed after 12 requests, from $42,324.22 to $43,891.83.
- **Sales:** 32 sale lines, $4,170.64 in revenue.
- **Stock purchases:** 22 stock orders, $2,603.03.
- **Total assets** (cash plus inventory at cost) grew from $50,000.00 to $50,705.14, so the business made $705.14 in gross profit over the evaluation.

### Strengths

- **Impossible constraints are recognized and explained.** All seven declines give the item and its earliest possible date. Request 17 is an example: "A4 paper (earliest 2025-04-18); Colored paper (earliest 2025-04-18); Paper napkins (earliest 2025-04-21); Paper cups (earliest 2025-04-18)." The customer can see exactly what would make the order possible.
- **Quotes are transparent.**
  - Every quote lists quantity, unit, unit price, and line total.
  - Discounts appear as a separate line with the threshold that earned them. Request 8, a $900 subtotal, earned 5%, saving $45.00.
  - Orders just below a threshold are told where the next tier starts.
- **Partial catalog matches still sell.** Request 9 contained envelopes that are not in the catalog, and request 20 contained tickets. Each reply named the unavailable items and fulfilled the rest, which matters when the customer gets no second turn.
- **Every sale is profitable and the books reconcile.** Each recorded sale matches its quote line, and every fulfilled order increased total assets. Request 9 shows the replenishment policy at work: cash fell by $41.30 because restocking cost more than the $37.50 sale, but inventory rose by more, so assets still grew.
- **No internal information is exposed.** Replies never show cost, margin, cash position, or system errors. Requests that are too large are declined with "we can't accommodate an order of this size right now", without mentioning cash, and any runtime error would return a generic apology.

### Areas for improvement

- **Late requests cluster near the deadline.** All seven declines were requested between April 8 and April 15. Most had an April 15 deadline; request 13 had April 10 and request 19 had April 20. Supplier lead time is four days for 101–1,000 units and seven days above that, and A4 paper appears in five of the seven declines. Stock was kept near the minimum, so large requests close to the deadline could not be met.
- **Request 2's balloons were treated as an unrelated request** rather than an unavailable paper-party product. The reply therefore said part of the request was "outside our services" instead of naming the balloons as unavailable.
- **"Printer paper" in request 3 stopped the order for a clarification**, even though Standard copy paper is a reasonable default.
- **Stock on order counts as stock on hand.** A stock order is recorded on its order date, so a later request in the same week can count goods that have not arrived yet.

## 3. Suggestions for further improvement

1. **Offer partial fulfillment and alternative dates.** When only some items are late, ship the on-time items now and quote the rest with their earliest date, instead of declining the whole order. Requests 13, 16, and 18 each had items that could ship on time. A customer agent that negotiates the date or the quantity would turn several of the seven declines into sales.
2. **Restock proactively from demand data.** Run `list_low_stock_items` daily and size reorders from the order sizes seen in `quote_requests.csv`, not from `min_stock_level` alone. A4 paper, cardstock, and colored paper were the bottlenecks, and holding a few thousand sheets of each would have covered most late requests.
3. **Track stock in transit.** Store an arrival date with each stock order (supplier date from `get_supplier_delivery_date`) and separate on-hand stock from stock on order. Ship dates would then be exact, and a request could be served from a delivery that is already on its way.
4. **Use stated defaults for common ambiguous product names.** Map terms such as "printer paper" to a default catalog item and state the assumption in the quote, instead of asking a clarification question that a one-shot customer never answers.
