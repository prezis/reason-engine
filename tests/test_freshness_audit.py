from pathlib import Path
import time
from reason.freshness_audit import run_audit, score_doc


def test_score_deprecated_is_red():
    level, _ = score_doc(Path("x"), {"status": "deprecated"}, incoming=0)
    assert level == "red"


def test_score_3_stale_votes_is_red():
    fm = {"session_feedback": [{"vote": "seems-stale"}] * 3}
    level, _ = score_doc(Path("x"), fm, incoming=0)
    assert level == "red"


def test_score_fresh_is_green():
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    fm = {"last_verified_entries": [{"session": "s", "ts": iso, "action": "cited-accurate"}]}
    level, _ = score_doc(Path("x"), fm, incoming=1)
    assert level == "green"


def test_audit_produces_report_structure(tmp_path):
    (tmp_path / "a.md").write_text("---\nkind: article\n---\n# Alpha\n")
    (tmp_path / "b.md").write_text("---\nkind: article\nstatus: deprecated\n---\n# Beta\n")
    report = run_audit(vault=tmp_path)
    assert "Freshness Audit" in report
    assert "\U0001f534" in report
    assert "b.md" in report
