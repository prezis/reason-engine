"""End-to-end freshness smoke: guard denies, logger records, proposal roundtrip."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_guard_denies_status_change_in_vault():
    hook = Path.home() / ".claude/enforcements/freshness-guard.py"
    r = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/home/palyslaf0s/ai/global-graph/patterns/foo.md",
                "old_string": "status: current",
                "new_string": "status: deprecated",
            },
        }).encode(),
        capture_output=True, timeout=5,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout.decode())
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_logger_records_vault_edit(tmp_path):
    hook = Path.home() / ".claude/enforcements/freshness-logger.py"
    env = {**os.environ, "FRESHNESS_LOG_PATH": str(tmp_path / "log.jsonl")}
    subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({
            "tool_name": "Write",
            "tool_input": {"file_path": "/home/palyslaf0s/ai/global-graph/research/x.md"},
            "session_id": "e2e",
        }).encode(),
        timeout=5, env=env,
    )
    recs = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert len(recs) == 1
    assert recs[0]["path"].endswith("x.md")


def test_proposal_writer_then_sessionstart_surfaces(tmp_path):
    from reason.freshness_proposals import ProposalWriter, ProposalType
    w = ProposalWriter(proposals_dir=tmp_path)
    path = w.write(
        target="patterns/foo.md",
        proposed_by="session-e2e",
        proposal_type=ProposalType.DEPRECATE,
        rationale="test",
        evidence=["test evidence"],
    )
    assert path.exists()
    hook = Path.home() / ".claude/enforcements/freshness-sessionstart.py"
    env = {**os.environ, "FRESHNESS_PROPOSALS_DIR": str(tmp_path)}
    r = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"session_id": "e2e"}).encode(),
        capture_output=True, timeout=5, env=env,
    )
    out = r.stdout.decode()
    assert path.stem in out


def test_schema_rejects_invalid_extensions_to_session_feedback():
    """If a session tries to write a malformed session_feedback entry via raw
    content, the schema validator (used elsewhere) catches it."""
    from reason.freshness import validate_schema, FreshnessError
    import pytest
    bad = {"kind": "article", "session_feedback": [
        {"session": "s", "ts": "t"}  # missing vote
    ]}
    with pytest.raises(FreshnessError, match="vote"):
        validate_schema(bad)
