import json, subprocess, sys
from pathlib import Path

HOOK = Path.home() / ".claude/enforcements/freshness-guard.py"

def _run(payload):
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps(payload).encode(),
                          capture_output=True, timeout=5)


def test_allows_edit_outside_vault():
    r = _run({
        "tool_name": "Edit",
        "tool_input": {"file_path": "/tmp/foo.md", "old_string": "x", "new_string": "y"},
    })
    assert r.returncode == 0
    assert r.stdout.decode().strip() == ""


def test_denies_status_mutation_in_vault():
    r = _run({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/home/palyslaf0s/ai/global-graph/patterns/foo.md",
            "old_string": "status: current",
            "new_string": "status: deprecated",
        },
    })
    assert r.returncode == 0
    out = json.loads(r.stdout.decode() or "{}")
    deny = out.get("hookSpecificOutput", {}).get("permissionDecision")
    assert deny == "deny", out


def test_allows_reference_count_bump_in_vault():
    r = _run({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/home/palyslaf0s/ai/global-graph/patterns/foo.md",
            "old_string": "reference_count: 5",
            "new_string": "reference_count: 6",
        },
    })
    assert r.returncode == 0
    out = r.stdout.decode()
    assert "deny" not in out.lower()
