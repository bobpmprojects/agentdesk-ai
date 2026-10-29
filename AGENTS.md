# AgentDesk — project rules

## Naming
- Product name: AgentDesk. Repo: agentdesk-ai. Python package/import name: `agentdesk`.
  Tagline: "Autonomous multi-agent customer service, resolved end to end within policy
  guardrails."

## Product
AgentDesk autonomously resolves customer service requests for a fictional online store
("Northwind Goods"). It handles multi-intent, multi-step conversations (e.g., "my blender
arrived broken, refund it and send the replacement to my new address") by coordinating
specialist agents that act on a mock backend. Goal: resolve correctly on the first
conversation, with zero policy violations.

## Stack (do not change without asking)
- Python 3.11, uv, Pydantic v2 for every agent input/output and tool schema.
- Agents: LangGraph (+ `langchain-core` for model/tool abstractions). Check the
  installed package version and current LangChain/LangGraph docs before writing code.
  Never guess APIs. Do NOT use the `langgraph-supervisor` package (no longer
  maintained).
- Orchestration: an explicit LangGraph `StateGraph`. The Supervisor is a node that
  routes to specialist agent nodes; shared typed state (Pydantic) flows between nodes.
- Model providers via env var `MODEL_PROVIDER = anthropic | openai | bedrock`, using
  each provider's LangChain integration. Model IDs live in config.
- All framework code lives in `agentdesk/agents/` behind a thin interface so the
  framework remains swappable.
- MODEL_PROVIDER env var = anthropic | openai | bedrock. Model IDs live in config.
- Mock backend: SQLite (customers, orders, shipments, refunds, addresses, audit_log).
- UI: Streamlit chat + side panel showing the live agent trace. Tests: pytest.

## Architecture rules
- Pattern: Supervisor + specialists (agents-as-tools). The Supervisor plans; specialists
  act. No free-form agent-to-agent chatter.
- Agents decide WHAT to do. A deterministic Policy Engine (plain Python) decides whether
  it is ALLOWED: refund caps, return windows, identity verification, cancel-before-ship.
  An LLM never approves a money movement or account change on its own.
- Every write tool (refund, cancel, address change) requires an idempotency key and writes
  to audit_log. Repeating the same request must not double-refund.
- Identity must be verified (order ID + email match) before any account or order data is
  read or changed.
- Grounded answers only: policy questions are answered from /policies docs with a cited
  section. If the answer isn't there, say so.
- Out-of-policy or ambiguous requests get a safe, explained "no" plus an alternative,
  or a ticket for later handling. Escalation is a measured failure mode, not the default.
- v1 runs locally only. Record/replay cache for LLM calls lives in fixtures/replay/ and is
  committed, so anyone can run the demo and evals with no API key.
- Trace every step: agent, tool, args, policy decision, latency, tokens, cost.
- Redact PII from logs. All data is synthetic; no real brands or people.
- Export the compiled LangGraph as Mermaid and render the graph in the Streamlit UI
  and `docs/ARCHITECTURE.md`, highlighting the active node during a run.

## Working style
- Plan first. Touch only the files needed for the current milestone.
- Say in 1–2 lines what you'll do and why before each change.
- On errors, state your hypothesis about the failing layer before fixing it.
- Simple and working beats clever.
- Never commit .env or API keys.
