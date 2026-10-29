# AgentDesk

Autonomous multi-agent customer service, resolved end to end within policy guardrails.

AgentDesk is a local, GitHub-ready demonstration for customer-service engineering teams.
It coordinates a Supervisor and typed specialists against a synthetic Northwind Goods
SQLite backend while deterministic Python policy rules authorize every write.

## What it demonstrates

- Supervisor plans with Identity, Orders, Returns & Refunds, Account, and
  Policy/Knowledge specialists; specialists return typed results rather than chatting.
- Order ID + email verification before protected reads or writes.
- Deterministic refund, cancellation, return-window, and address-change rules.
- Transactional, idempotent writes with an audit trail.
- Local Markdown BM25 policy retrieval with section citations.
- Code-first action/citation verification, then an LLM tone/promise check.
- Persisted multi-turn state and record/replay model fixtures.
- Streamlit chat with a redacted agent/tool trace.

All people, orders, addresses, and brands in the demo are synthetic.

## Requirements

- Python 3.11
- [`uv`](https://docs.astral.sh/uv/)
- An Anthropic, OpenAI, or Bedrock credential only when recording/live-running a new
  model request. Committed scenarios and CI need no credentials.

## Setup

```bash
uv sync --python 3.11
cp .env.example .env
uv run agentdesk-seed
```

For live OpenAI recording, edit the ignored `.env`:

```dotenv
MODEL_PROVIDER=openai
LLM_MODE=record
OPENAI_API_KEY=your-local-key
```

Use `MODEL_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`, or
`MODEL_PROVIDER=bedrock` with normal AWS credential resolution, for the other providers.
Model IDs are configured in `.env`; never commit that file.

## Run the Streamlit demo

Live/RECORD mode:

```bash
MODEL_PROVIDER=openai LLM_MODE=record uv run streamlit run agentdesk/ui/app.py
```

No-key REPLAY mode:

```bash
MODEL_PROVIDER=openai LLM_MODE=replay uv run streamlit run agentdesk/ui/app.py
```

The default replayed order-status credentials are:

- Order: `ORD-0002`
- Email: `customer001@northwind.test`
- Message: `Where is my order?`

## Run scripted milestone demos

M0 seed/policy/replay smoke:

```bash
uv run agentdesk-m0-demo
```

M1–M5 live recording:

```bash
MODEL_PROVIDER=openai uv run agentdesk-demo m1 --mode record
MODEL_PROVIDER=openai uv run agentdesk-demo m2 --mode record
MODEL_PROVIDER=openai uv run agentdesk-demo m3 --mode record
MODEL_PROVIDER=openai uv run agentdesk-demo m4 --mode record
MODEL_PROVIDER=openai uv run agentdesk-demo m5 --mode record
```

M1–M5 no-key replay:

```bash
MODEL_PROVIDER=openai uv run agentdesk-demo m1 --mode replay
MODEL_PROVIDER=openai uv run agentdesk-demo m2 --mode replay
MODEL_PROVIDER=openai uv run agentdesk-demo m3 --mode replay
MODEL_PROVIDER=openai uv run agentdesk-demo m4 --mode replay
MODEL_PROVIDER=openai uv run agentdesk-demo m5 --mode replay
```

## Tests, lint, and evals

```bash
uv run ruff check .
uv run pytest
MODEL_PROVIDER=openai LLM_MODE=replay uv run python -m agentdesk.evals
```

The eval command reports task resolution, policy violations, grounded action claims,
citation validity, unnecessary escalation, and replay determinism. It exits nonzero if
policy violations are above zero or another required quality gate fails.

GitHub Actions runs all three commands without API keys.

## Architecture

```text
Streamlit / scripted scenario
            |
       Supervisor
        /  |  \
 Identity  |  Policy/Knowledge -- BM25 --> policies/*.md
           |
 Orders / Returns & Refunds / Account
           |
     typed deterministic tools
           |
      Policy Engine (Python)
           |
 SQLite business write + audit_log (one transaction)
           |
 code-first Verifier --> LLM tone/promise check --> final reply
```

All Strands SDK imports and provider construction live in
`agentdesk/agents/strands_adapter.py`. Agent and tool boundaries use Pydantic v2 so the
framework can be replaced.

## Record/replay

`RECORD` hashes provider, model ID, normalized messages, template version, and tool-schema
version, then writes the complete synthetic request/response fixture under
`fixtures/replay/`. `REPLAY` serves only an exact hash match and never falls through to a
live model.

## Current limitations

- The intent planner supports the documented demo shapes rather than open-ended intent
  extraction.
- Return labels and replacements are local mock references, not carrier/warehouse calls.
- The generic Streamlit form does not expose every multi-intent and multi-turn control;
  the scripted demos cover those flows.
- BM25 is tuned for the six small policy documents and does not use stemming or semantic
  retrieval.
- Provider cost remains zero unless explicit pricing data is supplied.
