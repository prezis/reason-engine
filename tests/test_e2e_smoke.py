"""End-to-end smoke: trigger → hook → rewrite → slash-command protocol.

Gated by env var LIVE_REASON_E2E=1.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_REASON_E2E") != "1",
    reason="Live E2E disabled; set LIVE_REASON_E2E=1 to enable",
)


def test_hook_emits_reason_context_on_trigger():
    payload = {
        "prompt": "rozważ solidnie czy WAL mode w SQLite nadaje się do 100 write/sec "
                  "przy 2 concurrent readerach",
        "session_id": "e2e",
    }
    hook = Path.home() / ".claude/enforcements/reason-trigger.py"
    r = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload).encode(),
        capture_output=True, timeout=5,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout.decode())
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "REASON_TRIGGER" in ctx
    assert "mode=\"default\"" in ctx
    assert "WAL" in ctx


@pytest.mark.asyncio
async def test_judge_live_end_to_end():
    """Live Ollama. Requires qwen3.5:27b loaded."""
    sys.path.insert(0, str(Path.home() / "ai/local-ai-mcp"))
    from reason_judge import rubric_judge
    r = await rubric_judge(
        question="Is A better than B?",
        abstract_q="Comparison under constraints",
        worker_reports=[
            {"role": "pro",  "report": "A is better because of X, Y, Z."},
            {"role": "anti", "report": "B is better because of W."},
        ],
    )
    assert not r.degraded or r.raw is not None
    assert len(r.scores) == 2
    for role in ("pro", "anti"):
        for crit in ("correctness", "evidence_quality", "logical_soundness",
                      "completeness", "cites_or_synthesizes"):
            assert 1 <= r.scores[role][crit] <= 5
