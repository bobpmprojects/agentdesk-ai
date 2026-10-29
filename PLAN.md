# AgentDesk implementation plan

## Goal and target user

Build a local, GitHub-ready demonstration for customer-service engineering teams that shows AgentDesk autonomously resolving Northwind Goods requests end to end while deterministic policy guardrails prevent unauthorized actions.

## System boundaries and decisions

- Use Python 3.11, `uv`, Pydantic v2, SQLite, pytest, and Streamlit.
- Use the Supervisor + specialists-as-tools pattern. Specialists never chat directly with one another; they return typed results to the Supervisor.
- Use an explicit LangGraph `StateGraph`: a Supervisor node routes typed Pydantic
  shared state through specialist nodes. Keep LangGraph and LangChain dependencies
  behind `agentdesk/agents/`, and verify installed APIs against current official docs.
- Do not use the unmaintained `langgraph-supervisor` package.
- Use `langchain-core` model abstractions with `langchain-openai`,
  `langchain-anthropic`, and `langchain-aws` selected by `MODEL_PROVIDER`.
- Require successful order ID + email verification before any customer, order, shipment, refund, or address data is read or changed. Public policy-only questions do not access customer data and may run without identity.
- Let agents choose requested operations, but let only the deterministic Policy Engine authorize refunds, cancellations, replacements, and account changes.
- Require an idempotency key for every write. Perform the business write and its `audit_log` insert in one SQLite transaction.
- Redact email, address, and other PII before trace persistence or display.
- Store committed record/replay fixtures in `fixtures/replay/`; never commit credentials or `.env`.
- Before sending a reply, run deterministic verification of claimed actions and policy citations, followed by an LLM tone/unsupported-promise check. Allow at most one regeneration.

## Proposed repository structure

```text
agentdesk-ai/
├── .github/
│   └── workflows/
│       └── ci.yml
├── agentdesk/
│   ├── __init__.py
│   ├── config.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── interface.py          # Framework-neutral Agent protocol and runner
│   │   ├── langchain_adapter.py  # Provider-neutral live model adapter
│   │   ├── graph.py              # Explicit StateGraph and Pydantic shared state
│   │   ├── supervisor.py
│   │   ├── identity.py
│   │   ├── orders.py
│   │   ├── returns_refunds.py
│   │   ├── account.py
│   │   ├── policy_knowledge.py
│   │   └── verifier.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── agents.py
│   │   └── tools.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── identity.py
│   │   ├── orders.py
│   │   ├── returns_refunds.py
│   │   ├── account.py
│   │   ├── policy_search.py
│   │   └── support.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   ├── schema.sql
│   │   ├── repository.py
│   │   └── seed.py
│   ├── policy/
│   │   ├── __init__.py
│   │   └── engine.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   └── bm25.py
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── conversation.py
│   │   ├── replay.py
│   │   ├── tracing.py
│   │   └── verification.py
│   └── ui/
│       ├── __init__.py
│       └── app.py
├── docs/
│   └── ARCHITECTURE.md           # Exported compiled graph Mermaid diagram
├── policies/
│   ├── returns-and-refunds.md
│   ├── shipping-and-delivery.md
│   ├── cancellations.md
│   ├── damaged-or-wrong-items.md
│   ├── account-and-addresses.md
│   └── identity-and-privacy.md
├── fixtures/
│   ├── replay/                   # Committed, sanitized LLM recordings
│   └── eval_cases/
├── scripts/
│   └── seed_db.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evals/
├── .env.example
├── .gitignore
├── AGENTS.md
├── PLAN.md
├── README.md
├── pyproject.toml
└── uv.lock
```

The generated local SQLite database belongs under an ignored `.local/` directory. Seed generation is deterministic, so the database can be recreated rather than committed.

## Milestones

### M0 — Foundation and reproducible data

**Deliver**

- Scaffold the package, `pyproject.toml`, `uv.lock`, configuration, and test directories.
- Add validated settings for `MODEL_PROVIDER=anthropic|openai|bedrock`; keep provider model IDs in configuration.
- Define the framework-neutral agent interface, explicit LangGraph `StateGraph`, and
  LangChain provider adapter after checking installed APIs and current official docs.
- Add a record/replay layer keyed by normalized model request, provider, model ID, prompt/template version, and tool schema version.
- Create SQLite tables for `customers`, `orders`, `shipments`, `refunds`, `addresses`, `audit_log`, and conversation state.
- Add a deterministic seed command that creates exactly 50 synthetic customers and 150 orders across `processing`, `shipped`, `delivered`, and `delivered-damaged`.
- Add six policy documents with stable heading-based section IDs.
- Add shared Pydantic contracts and PII-redacted trace events.

**Demo**

Run one command to recreate the database, print seed counts/state distribution, index six policy docs, and replay a committed model fixture without an API key.

### M1 — Verified order-status vertical slice

**Deliver**

- Implement the Supervisor, Identity agent, and read-only Orders agent.
- Support “Where is my order?” and tracking requests.
- Enforce verification before order or shipment lookup.
- Add Streamlit chat and a live side panel showing the exported Mermaid graph with the
  active node highlighted, plus redacted plan, agent, tool, latency, token, cost, and
  policy-decision trace data.
- Return a grounded final response based only on typed tool output.

**Demo**

Enter an order ID and matching email, ask where the order is, and see the status/tracking response plus the full redacted trace. Repeat with a mismatched email and observe that no order lookup occurs.

### M2 — Returns/refunds and guarded writes

**Deliver**

- Implement the Returns & Refunds agent and deterministic Policy Engine.
- Encode these rules in Python: refund at most $200 within 30 days of delivery; above $200 offer store credit; cancellation only before shipment; identity required for all writes.
- Add cancel, return-label, refund, store-credit, and replacement write tools.
- Require idempotency keys and atomically append every attempted/committed write decision to `audit_log`.
- Return a safe explanation and permitted alternative for denied operations.

**Demo**

Resolve a damaged delivered order with an eligible refund/replacement, demonstrate an over-$200 store-credit alternative, deny a shipped cancellation, and replay the same write without duplicate effects.

### M3 — Account changes and multi-intent execution

**Deliver**

- Implement the Account agent for shipping-address changes and contact preferences.
- Enforce at most one shipping-address change per order and disallow address changes when shipment state makes the change ineffective.
- Extend the Supervisor to decompose one message into two or three typed intents, create dependencies, and execute specialists in order.
- Stop dependent steps safely after an identity or policy failure while allowing independent safe steps to continue.

**Demo**

Process “My blender arrived damaged; replace it and send the replacement to my new address” as an ordered plan: verify identity, assess replacement, update the eligible destination, create replacement, and summarize only committed actions.

### M4 — Grounded policy answers and final verifier

**Deliver**

- Implement local keyword/BM25 retrieval over Markdown headings and sections; do not add a vector database.
- Require the Policy/Knowledge agent to return section-level citations and explicitly say when the docs do not contain an answer.
- Add deterministic reply verification:
  1. Extract/receive structured action claims and confirm each against `audit_log`.
  2. Confirm every policy citation resolves to an existing document and section.
- Add the LLM verifier for tone and unsupported promises after deterministic checks pass.
- Regenerate a failed draft once, then send a safe fallback/escalation if the second draft fails.

**Demo**

Ask a policy question and receive section citations; then run fixtures containing a fabricated action and broken citation and show that neither reply is sent.

### M5 — Multi-turn conversation state

**Deliver**

- Persist a minimal typed conversation state: verified identity scope, active order, resolved/pending intents, prior tool outcomes, offered alternatives, and idempotency keys.
- Support safe references to prior turns without storing raw secrets in traces.
- Re-plan from the current state when the customer changes a choice, for example, “Actually, make it store credit.”
- Re-check policy at write time; never treat an earlier plan as authorization.

**Demo**

Start with an eligible replacement, change the choice to store credit on the next turn, and show that the Supervisor reuses context, rechecks policy, and performs only the newly confirmed action.

### M6 — Evals and CI

**Deliver**

- Add deterministic replay-backed evals covering happy paths, identity failures, policy boundaries, idempotency, multi-intent ordering, citations, verifier rejection, and multi-turn revisions.
- Score task resolution, policy violations, grounded action claims, citation validity, unnecessary escalation, and replay determinism.
- Add `.github/workflows/ci.yml` to install with `uv`, run unit/integration tests, and run the no-key replay eval suite on pushes and pull requests.
- Document local setup, provider selection, replay mode, demo scenarios, architecture, and limitations in `README.md`.

**Demo**

Run the same no-key eval command locally and in GitHub Actions, producing a concise score report with zero policy violations and no network/model credentials.

## Acceptance criteria

1. **Given** a clean checkout with no model API keys, **when** the M0 setup and replay commands run, **then** they create exactly 50 customers, 150 mixed-state orders, index six policy docs, and complete a recorded model interaction.
2. **Given** an order ID and non-matching email, **when** a customer asks about that order, **then** identity verification fails and no order, shipment, address, or refund lookup/write tool executes.
3. **Given** a matching order ID and email for a shipped order, **when** the customer asks where it is, **then** AgentDesk returns the database-backed status/tracking data and the Streamlit trace shows redacted, ordered agent/tool events.
4. **Given** one processing order and one shipped order, **when** cancellation is requested for each, **then** the processing order can be cancelled and audited while the shipped order is denied with an allowed alternative.
5. **Given** verified delivered orders inside the 30-day window priced at $200 and $200.01, **when** refunds are requested, **then** the first is eligible for automatic refund and the second produces a store-credit offer without issuing a cash refund.
6. **Given** an approved write request with one idempotency key, **when** that request is submitted twice, **then** exactly one business effect exists and both attempts are traceable to the same audit outcome.
7. **Given** a verified multi-intent request for a replacement and new shipping address, **when** the Supervisor executes it, **then** it uses dependency-ordered specialist steps and prevents a second address change for that order.
8. **Given** a policy answer draft, **when** its citation is valid, **then** the reply names the existing document section; **when** a citation or claimed action is fabricated, **then** deterministic verification blocks the reply before the LLM tone check.
9. **Given** a customer who selected replacement on one turn, **when** they say “Actually, make it store credit” on the next, **then** AgentDesk restores the relevant state, rechecks policy, avoids the replacement, and records only the confirmed store-credit action.
10. **Given** the committed replay fixtures and eval cases, **when** the documented eval command runs locally or in GitHub Actions, **then** all tests run without live model access and report zero policy violations, valid action claims, and valid citations.

## Planned Pydantic v2 contracts

These are boundary contracts, not implementation. All production models inherit `ContractModel`, reject unknown fields, and serialize enums by value. Secrets are accepted only at the identity boundary and must be redacted before tracing.

### Shared domain and trace schemas

```python
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class Intent(StrEnum):
    ORDER_STATUS = "order_status"
    TRACKING = "tracking"
    CANCEL = "cancel"
    RETURN = "return"
    REFUND = "refund"
    STORE_CREDIT = "store_credit"
    REPLACEMENT = "replacement"
    ADDRESS_CHANGE = "address_change"
    CONTACT_PREFERENCES = "contact_preferences"
    POLICY_QUESTION = "policy_question"


class OrderStatus(StrEnum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    DELIVERED_DAMAGED = "delivered-damaged"
    CANCELLED = "cancelled"


class Money(ContractModel):
    amount: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    currency: Literal["USD"] = "USD"


class VerifiedIdentity(ContractModel):
    customer_id: UUID
    order_id: str
    verified_at: datetime
    verification_id: UUID


class AgentContext(ContractModel):
    conversation_id: UUID
    turn_id: UUID
    customer_message: str = Field(min_length=1)
    identity: VerifiedIdentity | None = None
    active_order_id: str | None = None


class ActionClaim(ContractModel):
    action_type: str
    audit_id: UUID
    order_id: str | None = None
    description: str


class PolicyCitation(ContractModel):
    document: str
    section_id: str
    section_title: str
    quote: str = Field(min_length=1)


class PolicyDecision(ContractModel):
    decision_id: UUID
    operation: str
    allowed: bool
    rule_id: str
    reason: str
    alternative: str | None = None


class TraceEvent(ContractModel):
    event_id: UUID
    conversation_id: UUID
    turn_id: UUID
    timestamp: datetime
    event_type: Literal[
        "agent_start", "agent_end", "tool_start", "tool_end", "policy_decision",
        "verification", "model_call"
    ]
    agent: str
    tool: str | None = None
    args_redacted: dict[str, Any] = Field(default_factory=dict)
    policy_decision: PolicyDecision | None = None
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
```

### Agent input/output schemas

```python
class PlanStep(ContractModel):
    step_id: str
    intent: Intent
    specialist: Literal[
        "identity", "orders", "returns_refunds", "account", "policy_knowledge"
    ]
    depends_on: list[str] = Field(default_factory=list)
    requested_operation: str


class SupervisorInput(ContractModel):
    context: AgentContext
    conversation_state: "ConversationState | None" = None


class SupervisorOutput(ContractModel):
    intents: list[Intent] = Field(min_length=1, max_length=3)
    plan: list[PlanStep] = Field(min_length=1)
    draft_reply: str | None = None
    action_claims: list[ActionClaim] = Field(default_factory=list)
    citations: list[PolicyCitation] = Field(default_factory=list)


class IdentityAgentInput(ContractModel):
    context: AgentContext
    order_id: str = Field(min_length=1)
    email: SecretStr


class IdentityAgentOutput(ContractModel):
    verified: bool
    identity: VerifiedIdentity | None = None
    failure_reason: Literal["missing_credentials", "no_match", "locked"] | None = None


class OrdersAgentInput(ContractModel):
    context: AgentContext
    task: Literal["status", "tracking", "cancel"]
    idempotency_key: UUID | None = None


class OrdersAgentOutput(ContractModel):
    order_id: str
    status: OrderStatus
    carrier: str | None = None
    tracking_number_redacted: str | None = None
    estimated_delivery: date | None = None
    policy_decision: PolicyDecision | None = None
    action: ActionClaim | None = None


class ReturnsRefundsAgentInput(ContractModel):
    context: AgentContext
    task: Literal[
        "assess_return", "create_return_label", "refund", "store_credit", "replace"
    ]
    item_id: str
    reason: Literal["damaged", "wrong_item", "other"]
    idempotency_key: UUID | None = None


class ReturnsRefundsAgentOutput(ContractModel):
    eligible: bool
    resolution: Literal[
        "return_label", "refund", "store_credit", "replacement", "denied"
    ]
    amount: Money | None = None
    policy_decision: PolicyDecision
    action: ActionClaim | None = None
    explanation: str


class AddressInput(ContractModel):
    line1: str
    line2: str | None = None
    city: str
    region: str
    postal_code: str
    country_code: str = Field(min_length=2, max_length=2)


class AccountAgentInput(ContractModel):
    context: AgentContext
    task: Literal["change_shipping_address", "update_contact_preferences"]
    new_address: AddressInput | None = None
    email_opt_in: bool | None = None
    sms_opt_in: bool | None = None
    idempotency_key: UUID


class AccountAgentOutput(ContractModel):
    changed: bool
    policy_decision: PolicyDecision
    action: ActionClaim | None = None
    explanation: str


class PolicyKnowledgeAgentInput(ContractModel):
    context: AgentContext
    question: str = Field(min_length=1)
    max_sections: int = Field(default=5, ge=1, le=10)


class PolicyKnowledgeAgentOutput(ContractModel):
    answer: str
    citations: list[PolicyCitation]
    grounded: bool
    insufficient_policy: bool


class DeterministicVerification(ContractModel):
    action_claims_valid: bool
    citations_valid: bool
    errors: list[str] = Field(default_factory=list)


class LLMReplyCheck(ContractModel):
    tone_ok: bool
    unsupported_promises: list[str] = Field(default_factory=list)


class VerifierInput(ContractModel):
    conversation_id: UUID
    turn_id: UUID
    draft_reply: str
    action_claims: list[ActionClaim] = Field(default_factory=list)
    citations: list[PolicyCitation] = Field(default_factory=list)
    regeneration_count: int = Field(default=0, ge=0, le=1)


class VerifierOutput(ContractModel):
    approved: bool
    deterministic: DeterministicVerification
    llm_check: LLMReplyCheck | None = None
    regenerate: bool
    safe_fallback: str | None = None


class ConversationState(ContractModel):
    conversation_id: UUID
    identity: VerifiedIdentity | None = None
    active_order_id: str | None = None
    resolved_intents: list[Intent] = Field(default_factory=list)
    pending_intents: list[Intent] = Field(default_factory=list)
    offered_alternatives: list[str] = Field(default_factory=list)
    prior_actions: list[ActionClaim] = Field(default_factory=list)
    idempotency_keys: dict[str, UUID] = Field(default_factory=dict)
    updated_at: datetime
```

### Tool argument/result schemas

Every tool receives one `*Args` model and returns one `*Result` model. Protected tools validate `identity` in code even if the calling agent already performed that check.

```python
class ToolError(ContractModel):
    code: Literal[
        "identity_required", "not_found", "policy_denied", "invalid_state",
        "idempotency_conflict", "validation_error"
    ]
    message: str
    retryable: bool = False


class AuditRecord(ContractModel):
    audit_id: UUID
    idempotency_key: UUID
    operation: str
    outcome: Literal["committed", "denied", "duplicate", "failed"]
    policy_decision_id: UUID | None = None
    created_at: datetime


class VerifyIdentityArgs(ContractModel):
    order_id: str
    email: SecretStr


class VerifyIdentityResult(ContractModel):
    verified: bool
    identity: VerifiedIdentity | None = None
    error: ToolError | None = None


class GetOrderArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str


class GetOrderResult(ContractModel):
    order_id: str
    status: OrderStatus
    ordered_at: datetime
    delivered_at: datetime | None = None
    total: Money
    error: ToolError | None = None


class GetTrackingArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str


class GetTrackingResult(ContractModel):
    status: OrderStatus
    carrier: str | None = None
    tracking_number_redacted: str | None = None
    estimated_delivery: date | None = None
    error: ToolError | None = None


class CancelOrderArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    idempotency_key: UUID


class CancelOrderResult(ContractModel):
    cancelled: bool
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class AssessReturnArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    item_id: str
    reason: Literal["damaged", "wrong_item", "other"]


class AssessReturnResult(ContractModel):
    eligible: bool
    days_since_delivery: int | None = Field(default=None, ge=0)
    refundable_amount: Money | None = None
    decision: PolicyDecision
    error: ToolError | None = None


class CreateReturnLabelArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    item_id: str
    idempotency_key: UUID


class CreateReturnLabelResult(ContractModel):
    label_id: UUID | None = None
    label_reference: str | None = None
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class CreateRefundArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    item_id: str
    amount: Money
    idempotency_key: UUID


class CreateRefundResult(ContractModel):
    refund_id: UUID | None = None
    amount: Money | None = None
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class IssueStoreCreditArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    amount: Money
    idempotency_key: UUID


class IssueStoreCreditResult(ContractModel):
    credit_id: UUID | None = None
    amount: Money | None = None
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class CreateReplacementArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    item_id: str
    shipping_address_id: UUID
    idempotency_key: UUID


class CreateReplacementResult(ContractModel):
    replacement_order_id: str | None = None
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class ChangeShippingAddressArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    address: AddressInput
    idempotency_key: UUID


class ChangeShippingAddressResult(ContractModel):
    address_id: UUID | None = None
    change_count: int = Field(ge=0, le=1)
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class UpdateContactPreferencesArgs(ContractModel):
    identity: VerifiedIdentity
    email_opt_in: bool | None = None
    sms_opt_in: bool | None = None
    idempotency_key: UUID


class UpdateContactPreferencesResult(ContractModel):
    updated: bool
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class SearchPoliciesArgs(ContractModel):
    query: str = Field(min_length=1)
    max_sections: int = Field(default=5, ge=1, le=10)


class PolicySearchHit(ContractModel):
    citation: PolicyCitation
    score: float = Field(ge=0)


class SearchPoliciesResult(ContractModel):
    hits: list[PolicySearchHit]


class LookupAuditActionsArgs(ContractModel):
    conversation_id: UUID
    audit_ids: list[UUID]


class LookupAuditActionsResult(ContractModel):
    records: list[AuditRecord]
    missing_audit_ids: list[UUID] = Field(default_factory=list)


class ValidateCitationsArgs(ContractModel):
    citations: list[PolicyCitation]


class ValidateCitationsResult(ContractModel):
    valid: bool
    invalid_citations: list[PolicyCitation] = Field(default_factory=list)


class CreateSupportTicketArgs(ContractModel):
    identity: VerifiedIdentity | None = None
    conversation_id: UUID
    summary: str
    reason: Literal["ambiguous", "out_of_policy", "verification_failed", "system_error"]
    idempotency_key: UUID


class CreateSupportTicketResult(ContractModel):
    ticket_id: UUID | None = None
    audit: AuditRecord
    error: ToolError | None = None
```

The deterministic Policy Engine also accepts and returns typed contracts, but it is a plain Python service rather than an agent:

```python
class PolicyCheckInput(ContractModel):
    operation: Literal[
        "cancel", "return", "refund", "store_credit", "replace",
        "change_shipping_address", "update_contact_preferences"
    ]
    identity_verified: bool
    order_status: OrderStatus
    order_total: Money
    delivered_at: datetime | None = None
    address_change_count: int = Field(default=0, ge=0)


class PolicyCheckOutput(ContractModel):
    decision: PolicyDecision
```

## Implementation guardrails

- Tests target the framework-neutral interfaces; only graph/adapter tests import
  LangGraph or LangChain provider integrations.
- Keep the compiled graph export in `docs/ARCHITECTURE.md` synchronized with the graph
  rendered in Streamlit.
- Tool code, not prompts, owns identity assertions, policy checks, transactions, idempotency, and audit writes.
- Tool outputs are the only source for factual action claims in the final response.
- Policy citations use repository-relative document paths plus stable heading IDs; verifier validation reads the same indexed source files.
- Replay fixture inputs and outputs are synthetic and PII-scrubbed before commit.
- A failed verifier gets one regeneration only. A second failure returns a conservative fallback and creates a support ticket when appropriate.
- No milestone broadens the stack or introduces external infrastructure without approval.
