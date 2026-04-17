"""Trigger hook CLI — reads hook JSON stdin, emits hook JSON stdout."""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path.home() / ".claude/enforcements/reason-trigger.py"


def _run(payload: dict) -> dict:
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=5,
    )
    assert r.returncode == 0, r.stderr.decode()
    out = r.stdout.decode().strip()
    return json.loads(out) if out else {}


def test_no_trigger_emits_empty_output():
    out = _run({"prompt": "just a normal message", "session_id": "abc"})
    assert out == {}


def test_default_trigger_rewrites_prompt():
    out = _run({
        "prompt": "rozważ solidnie czy migracja do Postgres ma sens dla nas długoterminowo",
        "session_id": "abc",
    })
    assert out.get("hookSpecificOutput", {}).get("hookEventName") == "UserPromptSubmit"
    add_ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "REASON_TRIGGER" in add_ctx
    assert "default" in add_ctx
    assert "czy migracja do Postgres" in add_ctx


def test_debate_trigger_rewrites_with_mode():
    out = _run({
        "prompt": "debatuj whether microservices actually help for small teams below 20 people",
        "session_id": "abc",
    })
    add_ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "REASON_TRIGGER" in add_ctx
    assert "debate" in add_ctx
