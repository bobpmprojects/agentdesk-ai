"""M6: the LLM plans from free text; code still verifies and approves every action."""

import pytest

from agentdesk.agent_cases import CASES, PARAPHRASES, check_case, run_case, run_paraphrases
from agentdesk.agents.graph import _UNSUPPORTED_REFUND_CLAIM
from agentdesk.agents.planner import parse_plan
from agentdesk.runtime.redaction import redact_free_text


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_free_text_use_case_end_to_end(case) -> None:
    outputs, refunds = run_case(case, "replay")
    assert check_case(case, outputs, refunds) == []


def test_prompt_injection_cannot_move_money() -> None:
    case = next(case for case in CASES if case.id == "uc4-injection")
    outputs, refunds = run_case(case, "replay")
    assert refunds == 0
    assert outputs[0].steps[0].outcome == "denied"
    assert "refund-cap-200" in outputs[0].steps[0].detail


def test_asking_twice_writes_one_refund() -> None:
    case = next(case for case in CASES if case.id == "uc1-refund-under-cap")
    _, refunds = run_case(case, "replay")
    assert refunds == 1


def test_planner_reads_intent_from_paraphrases() -> None:
    results = run_paraphrases("replay")
    misses = [(m, e, p) for m, e, p in results if set(e) != set(p)]
    assert len(results) == len(PARAPHRASES)
    assert misses == []


def test_plan_schema_has_no_way_to_name_an_amount_or_approval() -> None:
    assert parse_plan('{"intents": ["refund"], "amount": 500}') is None
    assert parse_plan('{"intents": ["approve_refund"]}') is None
    plan = parse_plan('```json\n{"intents": ["refund"], "reason": "damaged"}\n```')
    assert plan is not None and plan.intents == ["refund"]


def test_free_text_pii_is_redacted_before_the_model() -> None:
    redacted = redact_free_text(
        "Email me at jane.doe@example.com or 415-555-0199, ship to 900 New Street."
    )
    assert "jane.doe" not in redacted and "555" not in redacted and "900 New" not in redacted
    assert "[EMAIL]" in redacted and "[PHONE]" in redacted and "[ADDRESS]" in redacted


def test_output_guard_catches_refund_claims_only() -> None:
    assert _UNSUPPORTED_REFUND_CLAIM.search("Your refund has been processed.")
    assert _UNSUPPORTED_REFUND_CLAIM.search("We've refunded you in full.")
    assert not _UNSUPPORTED_REFUND_CLAIM.search(
        "We cannot automatically approve cash refunds for amounts above $200."
    )
    assert not _UNSUPPORTED_REFUND_CLAIM.search("I haven't processed any refund.")
