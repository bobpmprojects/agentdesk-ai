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

## M3 — Account changes and multi-intent execution

### Built

- Account specialist and typed tools for shipping-address and contact-preference changes.
- Deterministic one-address-change-per-order and before-shipment policy checks, with an
  explicit replacement-destination path.
- Supervisor decomposition and dependency ordering for refund/address and
  replacement/address requests.
- Safe partial execution: independent eligible work continues when another intent is
  policy-denied.
- Scripted M3 damaged-blender refund plus shipping-address request.

### Files changed

- Account: `agentdesk/agents/account.py`, `agentdesk/tools/account.py`
- Planning/contracts/policy: `agentdesk/agents/supervisor.py`,
  `agentdesk/schemas/{agents,tools}.py`, `agentdesk/policy/engine.py`
- Persistence: `agentdesk/db/repository.py`
- Demo/tests: `agentdesk/scenarios.py`,
  `tests/integration/test_m3_multi_intent.py`
- Replay: `fixtures/replay/`

### Verification

- `uv run pytest`: **18 passed**
- M3 OpenAI RECORD then REPLAY: **final outputs identical**
- Streamlit headless health check: **passed**

### Acceptance criteria met

- **AC7:** a replacement/address request executes verify → assess → address →
  replacement, and a subsequent address change is policy-denied; independent
  refund/address requests safely preserve the eligible refund.

### Known gaps or shortcuts

- M3 intent extraction is deterministic keyword routing for the two planned demo shapes;
  a model-generated plan is intentionally deferred in favor of predictable guardrails.
- Address validation is structural and synthetic; no postal-service validation is used.

## M4 — Grounded policy answers and final verifier

### Built

- In-process BM25 retrieval over stable Markdown policy sections, with meaningful-term
  coverage filtering and no vector database.
- Policy/Knowledge specialist returning resolvable section citations or an explicit
  “not in policy” response.
- Code-first verifier proving every claimed action is a committed `audit_log` row and
  every citation matches an existing document, heading, title, and quoted text.
- LLM tone/unsupported-promise check only after deterministic checks pass.
- One regeneration maximum followed by a conservative fallback.
- Policy routing in Streamlit and a scripted cited/uncovered M4 scenario.

### Files changed

- Retrieval/tools: `agentdesk/retrieval/bm25.py`,
  `agentdesk/tools/{policy_search,support}.py`
- Agents/runtime: `agentdesk/agents/{policy_knowledge,verifier,supervisor}.py`
- Contracts/persistence/UI: `agentdesk/schemas/{agents,tools}.py`,
  `agentdesk/db/repository.py`, `agentdesk/ui/app.py`
- Demo/tests: `agentdesk/scenarios.py`,
  `tests/integration/test_m4_policy_verifier.py`
- Replay: `fixtures/replay/`

### Verification

- `uv run pytest`: **22 passed**
- M4 OpenAI RECORD then REPLAY: **both final outputs identical**
- Streamlit headless health check: **passed**

### Acceptance criteria met

- **AC8:** valid policy answers carry real section citations; fabricated citations and
  action claims fail deterministic verification before an LLM check.

### Known gaps or shortcuts

- The final verifier is wired into the policy reply path and is directly testable for
  action replies; existing M1–M3 scripted reply paths are not retroactively re-recorded
  with extra verifier calls to avoid unapproved API spend.
- BM25 uses a small deterministic tokenizer and relevance threshold suitable for six
  documents, not language-aware stemming or synonyms.

## M5 — Multi-turn conversation state

### Built

- Typed SQLite conversation-state store containing verified scope, active order,
  pending/resolved intents, alternatives, prior actions, and stable idempotency keys.
- PII-minimized persistence: raw email and address values are not stored in state.
- First-turn eligibility flow that records a preferred replacement without performing
  the write.
- Follow-up re-planning for “actually, make it store credit,” including a fresh
  deterministic policy check at write time.
- Scripted two-turn M5 scenario.

### Files changed

- State/contracts: `agentdesk/runtime/conversation.py`,
  `agentdesk/schemas/agents.py`
- Orchestration/demo: `agentdesk/agents/supervisor.py`,
  `agentdesk/scenarios.py`
- Tests: `tests/integration/test_m5_conversation_state.py`
- Replay: `fixtures/replay/`

### Verification

- `uv run pytest`: **23 passed**
- M5 OpenAI RECORD then REPLAY: **both turn outputs identical**
- Streamlit headless health check: **passed**

### Acceptance criteria met

- **AC9:** a pending replacement can be changed to store credit on the next turn;
  AgentDesk reloads state, rechecks policy, creates no replacement, and records only
  store credit.

### Known gaps or shortcuts

- The scripted service path demonstrates durable multi-turn behavior; the generic
  Streamlit form does not yet expose controls for every resolution transition.
- Conversation state is local SQLite only, with no expiry or multi-process locking
  beyond SQLite transactions.

## M6 — Evals, CI, and documentation

### Built

- Five committed replay eval cases covering order status, refund boundaries,
  multi-intent partial success, policy grounding, and multi-turn revision.
- Machine-readable eval runner scoring task resolution, policy violations, grounded
  actions, citation validity, unnecessary escalation, and replay determinism.
- Nonzero eval exit when policy violations or another required quality gate fails.
- GitHub Actions workflow running frozen `uv` install, Ruff, pytest, and no-key replay
  evals.
- Complete setup, provider, live/replay demo, architecture, testing, and limitations
  documentation.
- Ruff dependency and repository-wide safe style normalization.

### Files changed

- CI/tooling: `.github/workflows/ci.yml`, `pyproject.toml`, `uv.lock`
- Evals: `agentdesk/evals.py`, `fixtures/eval_cases/core.json`,
  `tests/evals/test_replay_evals.py`
- Documentation: `README.md`
- Quality normalization: Python imports and equivalent Ruff-safe constructor/style
  fixes across `agentdesk/` and `tests/`

### Verification

- `uv run ruff check .`: **passed**
- `uv run pytest`: **24 passed**
- Replay evals: **5/5 resolved, 0 policy violations, 1.0 grounded actions,
  1.0 citation validity, 0 unnecessary escalations, deterministic**
- Streamlit headless replay health check: **passed**

### Acceptance criteria met

- **AC10:** committed fixtures and evals run without live model access locally and in
  GitHub Actions, with zero policy violations and valid claims/citations.

### Known gaps or shortcuts

- Evals are five deterministic high-value scenarios rather than a statistically broad
  natural-language benchmark.
- CI is authored and locally validated but cannot be observed on GitHub until a remote
  exists and the repository is pushed.

## Framework migration — Strands to LangGraph

### Built

- Replaced Strands with LangGraph 1.2.18, LangChain Core 1.7.2, and the installed
  OpenAI, Anthropic, and AWS LangChain provider integrations.
- Added one explicit compiled `StateGraph` with Supervisor, Identity, Orders,
  Returns & Refunds, Account, Policy/Knowledge, Verifier, Memory, model-reply, and
  finalize nodes.
- Added shared Pydantic `AgentGraphState`, conditional routing, and active-node
  callbacks while preserving the public Supervisor API.
- Preserved the deterministic Policy Engine, audit/idempotency behavior, conversation
  state, and hash-keyed RECORD/REPLAY fixtures.
- Exported the compiled graph as Mermaid in `docs/ARCHITECTURE.md` and rendered the
  same graph in Streamlit with active-node highlighting.

### Verification

- `uv run ruff check .`: **passed**
- `uv run pytest`: **27 passed**
- Replay evals: **5/5 resolved, 0 policy violations, deterministic**
- Streamlit graph render and active-node execution path: **visually verified**
