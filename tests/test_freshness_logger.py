import json, subprocess, sys
from pathlib import Path

HOOK = Path.home() / ".claude/enforcements/freshness-logger.py"

def _run(payload):
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps(payload).encode(),
                          capture_output=True, timeout=5)


def test_hook_logs_vault_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHNESS_LOG_PATH", str(tmp_path / "log.jsonl"))
    r = _run({
        "tool_name": "Edit",
        "tool_input": {"file_path": "/home/palyslaf0s/ai/global-graph/patterns/foo.md"},
        "session_id": "test-session",
    })
    assert r.returncode == 0, r.stderr.decode()
    log = (tmp_path / "log.jsonl").read_text().strip()
    assert log
    rec = json.loads(log)
    assert rec["tool"] == "Edit"
    assert rec["session_id"] == "test-session"
    assert "global-graph" in rec["path"]


def test_hook_ignores_non_vault_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHNESS_LOG_PATH", str(tmp_path / "log.jsonl"))
    r = _run({
        "tool_name": "Edit",
        "tool_input": {"file_path": "/tmp/random.md"},
        "session_id": "test-session",
    })
    assert r.returncode == 0
    assert not (tmp_path / "log.jsonl").exists() or not (tmp_path / "log.jsonl").read_text()
