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
