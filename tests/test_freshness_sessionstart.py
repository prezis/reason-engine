import json, subprocess, sys
from pathlib import Path

HOOK = Path.home() / ".claude/enforcements/freshness-sessionstart.py"


def test_surfaces_pending_proposals(tmp_path, monkeypatch):
    prop = tmp_path / "pending-2026-04-18-foo-deprecate-abc123.md"
    prop.write_text("---\ntarget: foo.md\n---\n# Proposal\n")
    monkeypatch.setenv("FRESHNESS_PROPOSALS_DIR", str(tmp_path))
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps({"session_id": "test"}).encode(),
                       capture_output=True, timeout=5, env={**__import__("os").environ, "FRESHNESS_PROPOSALS_DIR": str(tmp_path)})
    assert r.returncode == 0
    out = r.stdout.decode()
    assert "pending-2026-04-18-foo-deprecate-abc123" in out
    data = json.loads(out) if out else {}
    ctx = data.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "pending proposal" in ctx.lower()


def test_empty_proposals_dir_is_silent(tmp_path, monkeypatch):
    import os
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps({"session_id": "test"}).encode(),
                       capture_output=True, timeout=5,
                       env={**os.environ, "FRESHNESS_PROPOSALS_DIR": str(tmp_path)})
    assert r.returncode == 0
    assert r.stdout.decode().strip() == ""
