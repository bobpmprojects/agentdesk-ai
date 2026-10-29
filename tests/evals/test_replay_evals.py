from pathlib import Path

from agentdesk.config import ROOT_DIR, Settings
from agentdesk.evals import run_evals


def test_replay_eval_suite_has_zero_policy_violations(tmp_path: Path) -> None:
    report = run_evals(
        Settings(
            model_provider="openai",
            llm_mode="replay",
            database_path=tmp_path / "eval.db",
            replay_dir=ROOT_DIR / "fixtures" / "replay",
        )
    )

    assert report.failed_cases == []
    assert report.task_resolution == 1
    assert report.policy_violations == 0
    assert report.grounded_action_claims == 1
    assert report.citation_validity == 1
    assert report.unnecessary_escalations == 0
    assert report.replay_deterministic is True
