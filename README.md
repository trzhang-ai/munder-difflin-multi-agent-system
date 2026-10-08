# AI Order Processing Assistant | AI 订单处理助手

[English](#english) · [简体中文](#简体中文)

## English

A customer sends a purchase request in plain English. The system identifies the products and quantities, checks whether the order can be delivered, and returns a quote, a clarification question, or a reason it cannot proceed.

This Python project connects language-model agents with inventory, pricing, and order-recording functions. The included examples use simulated office-supply orders.

**Customer message → Understand the request → Check availability and price → Respond or record the order**

### What it produces

A saved example, request 10:

| Input | Saved result |
|---|---|
| 500 sheets of glossy paper and 300 sheets of cardstock, needed by April 15 | Quote: **$181.25**; expected delivery: **April 12**; order confirmed in the simulation |

The same workflow can ask which product a customer means or explain that a requested deadline cannot be met. Examples and replies come directly from [the saved results](test_results.csv).

### Try it without an API key

With Python 3.12+ installed:

```sh
git clone https://github.com/trzhang-ai/munder-difflin-multi-agent-system.git
cd munder-difflin-multi-agent-system
python3 demo.py
```

This preview needs only Python, with no extra packages. It displays the original customer message, its saved status and reply, and a summary of all 20 saved requests. It reads existing results without making a model call.

Try the other outcomes:

```sh
python3 demo.py --case clarification
python3 demo.py --case deadline
```

`clarification` shows a request needing product details; `deadline` shows a request whose delivery deadline cannot be met.

### Run a new request

Use Python 3.12+ and `uv`. Install the dependencies and create your local configuration:

```sh
uv sync --locked
cp .env.example .env
```

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`. Set `OPENAI_BASE_URL` if your provider uses a custom OpenAI-compatible endpoint. The model must support tool calling and the configuration in [model_config.py](model_config.py).

```sh
uv run python demo.py --live \
  --request "Please quote 100 sheets of A4 paper, delivered by April 15, 2025." \
  --date 2025-04-01
```

This example requests a quote for 100 sheets of A4 paper by April 15, 2025, with April 1, 2025 as the request date. The command creates the local sample database on first use, calls the model, and prints the request, status, and customer reply. A feasible request returns `quoted` with item prices, a total, and a delivery estimate. Missing information returns `needs_clarification`; an impossible deadline returns `unfulfillable` with an explanation. This mode stops at the quote, before recording a sale. Model calls use your provider’s API allowance.

### Run the full workflow

```sh
uv run python operations.py
```

This runs all 20 sample requests and automatically accepts feasible orders in the simulation. It resets the local database and overwrites `test_results.csv`.

You get:

- **Terminal output:** each request, its outcome, and the customer reply.
- **`test_results.csv`:** a row per request with its status, reply, and balance snapshots.
- **`munder_difflin.db`:** local inventory and recorded purchase/sale transactions.

The existing saved run contains:

| Outcome | Requests |
|---|---:|
| Fulfilled | 12 |
| Deadline could not be met | 7 |
| Clarification needed | 1 |

These counts describe one simulated run. New model runs can produce different wording and classifications.

### Engineering demonstrated

- **Structured extraction:** turn free text into validated product, quantity, and delivery fields; keep conversation context for follow-up questions.
- **Tool-based decisions:** use Python calculations and database records for inventory and prices while the model handles language.
- **Workflow coordination:** route requests through specialist agents, handle incomplete or infeasible orders, and keep quote review separate from order recording.

**Stack:** Python · smolagents · Pydantic · pandas · SQLAlchemy · SQLite

For implementation details, see [architecture.md](architecture.md): components, API usage, file guide, business rules, and [current limitations](architecture.md#known-limits), including order retries and generated-quote consistency.

## 简体中文

客户用英文描述采购需求，系统识别商品和数量、检查能否按时交付，并返回报价、需要补充的信息，或无法履行的原因。

这个 Python 项目将语言模型代理与库存检查、价格计算和订单记录功能连接起来。随附示例使用模拟的办公用品订单。

**客户消息 → 理解需求 → 检查库存与价格 → 回复客户或记录订单**

### 运行后会得到什么

已保存的第 10 条请求示例：

| 输入 | 已保存的结果 |
|---|---|
| 采购 500 张光面纸和 300 张卡纸，要求 4 月 15 日前送达 | 报价 **$181.25**；预计 **4 月 12 日**送达；模拟订单已确认 |

同一流程也可以询问客户具体需要哪种商品，或解释为何无法满足交期。示例与回复均来自[已保存的运行结果](test_results.csv)。

### 无需 API Key，直接查看效果

安装 Python 3.12 或更高版本后运行：

```sh
git clone https://github.com/trzhang-ai/munder-difflin-multi-agent-system.git
cd munder-difflin-multi-agent-system
python3 demo.py
```

预览仅依赖 Python，无需安装额外软件包。它会显示客户原始请求、已保存的处理状态和回复，以及全部 20 条请求的结果汇总。此模式读取已有记录，不会调用模型。

查看另外两种处理结果：

```sh
python3 demo.py --case clarification
python3 demo.py --case deadline
```

`clarification` 展示需要补充商品信息的请求；`deadline` 展示无法满足交期的请求。

### 处理一条新请求

准备 Python 3.12 或更高版本以及 `uv`，然后安装依赖并创建本地配置：

```sh
uv sync --locked
cp .env.example .env
```

在 `.env` 中填写 `OPENAI_API_KEY` 和 `OPENAI_MODEL`。如果模型服务商提供自定义的 OpenAI 兼容接口，再设置 `OPENAI_BASE_URL`。所选模型需要支持工具调用，以及 [model_config.py](model_config.py) 中的配置。

```sh
uv run python demo.py --live \
  --request "Please quote 100 sheets of A4 paper, delivered by April 15, 2025." \
  --date 2025-04-01
```

这条命令以 2025 年 4 月 1 日为请求日期，为 100 张 A4 纸询价，要求 4 月 15 日前送达。首次使用时会创建本地示例数据库，随后调用模型，并显示请求、状态与客户回复：

- `quoted`：可以履行，返回商品价格、总额和预计交期。
- `needs_clarification`：信息不足，返回需要客户补充的问题。
- `unfulfillable`：无法满足交期等履行条件，返回原因。

此模式只生成报价，不记录销售交易。模型调用会使用服务商的 API 配额。

### 运行完整流程

```sh
uv run python operations.py
```

这会处理全部 20 条样例请求，并在模拟中自动接受能够履行的订单。运行时会重置本地数据库，并覆盖 `test_results.csv`。

运行结果包括：

- **终端输出：**每条请求、处理结果和客户回复。
- **`test_results.csv`：**每条请求对应一行，包含状态、回复以及现金和库存金额快照。
- **`munder_difflin.db`：**保存本地库存及采购、销售交易记录的数据库。

目前保存的一次运行结果为：

| 处理结果 | 请求数 |
|---|---:|
| 已完成 | 12 |
| 无法满足交期 | 7 |
| 需要补充信息 | 1 |

这些数字仅描述一次模拟运行。重新调用模型时，回复措辞和分类可能不同。

### 项目体现的工程能力

- **结构化提取：**把自然语言转换为经过校验的商品、数量和交期字段，并保留会话上下文以处理后续问题。
- **基于工具的决策：**模型负责理解与表达；Python 计算和数据库记录负责库存与价格。
- **流程编排：**协调不同职责的代理，处理信息不完整或无法履行的订单，并将报价审核与订单记录分开。

**技术栈：**Python · smolagents · Pydantic · pandas · SQLAlchemy · SQLite

实现细节见 [architecture.md](architecture.md)，包括组件职责、API 用法、文件说明、业务规则和[当前限制](architecture.md#known-limits)，其中说明了订单重试和生成报价一致性等问题。
