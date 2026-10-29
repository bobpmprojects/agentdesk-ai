# AgentDesk build log

## M0 — Foundation and reproducible data

### Built

- Python 3.11 `uv` project with Pydantic v2, Streamlit, pytest, and
  `strands-agents[anthropic,openai]`.
- Validated Anthropic/OpenAI/Bedrock provider switch and model IDs in configuration.
- Framework-neutral agent protocol and a Strands 1.62.0 adapter based on inspected
  installed signatures.
- Strict SHA-256-keyed RECORD/REPLAY cache. RECORD persists every request and response;
  REPLAY raises on a missing or mismatched fixture and never calls a live model.
- SQLite schema and deterministic seed data with 50 customers, 150 orders, mixed states,
  shipments, addresses, refunds, audit log, and conversation-state storage.
- Six policy Markdown documents with stable section IDs and a deterministic section
  loader.
- Shared Pydantic contracts, PII-redacted tracing, a no-key M0 demo, and a minimal
  Streamlit boot target.

### Files changed

- Project: `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, `README.md`,
  `PLAN.md`
- Package: `agentdesk/config.py`, `agentdesk/demo.py`, `agentdesk/agents/`,
  `agentdesk/schemas/`, `agentdesk/runtime/`, `agentdesk/db/`, `agentdesk/retrieval/`,
  `agentdesk/ui/`
- Content/data: `policies/`, `fixtures/replay/`
- Tests: `tests/unit/test_m0_foundation.py`

### Verification

- `uv run pytest`: **6 passed**
- M0 demo: **50 customers, 150 orders, four required states, six policy docs, replay
  response matched**
- Streamlit headless health check: **passed**

### Acceptance criteria met

- **AC1:** clean, no-key replay setup creates exact seed counts, indexes six policy
  documents, and serves a committed model response fixture.

### Known gaps or shortcuts

- The M0 fixture uses a deterministic fake live callback to prove recording without
  spending API credits; real provider recordings begin with the required M1 scenario.
- Cost remains zero unless a provider supplies explicit pricing; token counts are
  captured by the Strands adapter.
- The Streamlit screen is intentionally a foundation placeholder until M1.

## M1 — Verified order-status vertical slice

### Built

- Typed Supervisor, Identity, and Orders agents with specialists invoked in a fixed,
  dependency-ordered plan.
- Order ID + email verification gate before order or shipment data access.
- Read-only order and tracking tools backed by the SQLite repository.
- Grounded final-reply model request containing only verified typed order facts.
- Streamlit chat form and live redacted trace panel.
- Scripted `m1` demo with real-provider RECORD and strict REPLAY modes.

### Files changed

- Agents and tools: `agentdesk/agents/{identity,orders,supervisor}.py`,
  `agentdesk/tools/{identity,orders}.py`
- Contracts/data: `agentdesk/schemas/{agents,tools}.py`,
  `agentdesk/db/repository.py`
- Demo/UI: `agentdesk/scenarios.py`, `agentdesk/ui/app.py`, `pyproject.toml`
- Tests: `tests/integration/test_m1_order_status.py`
- Replay: `fixtures/replay/`

### Verification

- `uv run pytest`: **8 passed**
- M1 OpenAI RECORD then REPLAY: **final outputs identical**
- Streamlit headless health check: **passed**

### Acceptance criteria met

- **AC2:** mismatched identity stops before every protected order/shipment lookup.
- **AC3:** a verified shipped order returns database-backed status/tracking data and a
  redacted ordered trace.

### Known gaps or shortcuts

- M1 intent detection is deliberately limited to the order-status/tracking vertical
  slice; multi-intent planning arrives in M3.
- Provider-reported token counts are captured, but provider pricing is not inferred.

## M2 — Returns/refunds and guarded writes

### Built

- Plain-Python Policy Engine enforcing identity, $200 refund cap, 30-day delivery
  window, and cancel-before-shipment.
- Typed cancellation, return assessment/label, refund, store-credit, and replacement
  tools.
- Atomic SQLite business writes plus `audit_log` entries, with unique idempotency keys
  returning the original audit outcome on retries.
- Returns & Refunds specialist and Supervisor refund plan with safe denied alternatives.
- Scripted M2 scenario for a $149 committed refund and a denied $350 cash refund with
  store-credit offer.

### Files changed

- Policy/contracts: `agentdesk/policy/`, `agentdesk/schemas/{common,agents,tools}.py`
- Agents/tools: `agentdesk/agents/{orders,returns_refunds,supervisor}.py`,
  `agentdesk/tools/{orders,returns_refunds}.py`
- Persistence/data: `agentdesk/db/{repository,seed}.py`
- Demo/tests: `agentdesk/scenarios.py`,
  `tests/integration/test_m2_guarded_writes.py`,
  `tests/unit/test_m2_policy_engine.py`
- Replay: `fixtures/replay/`

### Verification

- `uv run pytest`: **15 passed**
- M2 OpenAI RECORD then REPLAY: **both final outputs identical**
- Streamlit headless health check: **passed**

### Acceptance criteria met

- **AC4:** processing cancellation commits and audits; shipped cancellation is denied
  with the return alternative.
- **AC5:** $200 is cash-refund eligible at the 30-day boundary; $200.01 is denied with
  store credit offered.
- **AC6:** repeating one refund idempotency key creates one refund and resolves to one
  audit outcome.

### Known gaps or shortcuts

- Return labels and replacements are local mock references represented by committed
  audit effects; there is no external carrier or fulfillment integration.
- The provider may phrase fulfillment timing conversationally in M2; unsupported-promise
  enforcement is added by the M4 verifier.
