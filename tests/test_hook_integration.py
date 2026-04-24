"""End-to-end hook test.

Spawns the hook as a subprocess, pipes a simulated PostToolUse(Agent)
payload into stdin, and asserts:
  - exit code is 0 (WARN mode — never blocks)
  - validation record is appended to the per-session JSONL file
  - violations are emitted for a known-bad worker output
  - no record is written for non-REASON Agent dispatches
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HOOK = Path.home() / ".claude" / "enforcements" / "reason-validator.py"
FIXTURES = Path(__file__).parent / "fixtures"


def _invoke_hook(payload: dict, env_overrides: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


@pytest.mark.skipif(not HOOK.exists(), reason="hook not installed")
def test_hook_logs_validated_report_for_good_worker(tmp_path):
    report_text = (FIXTURES / "worker_adversarial_ok.md").read_text()
    payload = {
        "session_id": "testsess-good",
        "tool_name": "Agent",
        "tool_input": {
            "description": "REASON worker: adversarial red-team",
            "subagent_type": "general-purpose",
            "prompt": "…",
        },
        "tool_response": report_text,
    }
    res = _invoke_hook(payload, {"REASON_VALIDATOR_LOG_DIR": str(tmp_path)})
    assert res.returncode == 0, res.stderr

    log = tmp_path / "testsess-good" / "validation.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().splitlines()[0])
    assert record["role"] == "adversarial"
    # The fixture fails structural validation because its cited paths may not
    # resolve on this machine, but the hook must still log the record — and
    # tool_uses_count + citations_checked MUST be sane.
    assert record["tool_uses_count"] >= 5
    assert record["citations_checked"] >= 2


@pytest.mark.skipif(not HOOK.exists(), reason="hook not installed")
def test_hook_fails_with_violations_for_bad_worker(tmp_path):
    report_text = (FIXTURES / "worker_empirical_bad_nocites.md").read_text()
    payload = {
        "session_id": "testsess-bad",
        "tool_name": "Agent",
        "tool_input": {
            "description": "REASON worker: methodological skeptic",
            "subagent_type": "general-purpose",
            "prompt": "…",
        },
        "tool_response": report_text,
    }
    res = _invoke_hook(payload, {"REASON_VALIDATOR_LOG_DIR": str(tmp_path)})
    assert res.returncode == 0, "WARN mode must never block"
    # WARN was emitted to stderr
    assert "FAIL" in res.stderr
    # Log still got written
    log = tmp_path / "testsess-bad" / "validation.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().splitlines()[0])
    assert record["ok"] is False
    kinds = {v["kind"] for v in record["violations"]}
    assert "no_tool_uses" in kinds or "insufficient_tool_uses" in kinds


@pytest.mark.skipif(not HOOK.exists(), reason="hook not installed")
def test_hook_ignores_non_reason_agent_dispatch(tmp_path):
    payload = {
        "session_id": "testsess-unrelated",
        "tool_name": "Agent",
        "tool_input": {
            "description": "Run a security review",
            "subagent_type": "security-reviewer",
            "prompt": "…",
        },
        "tool_response": "some other agent output",
    }
    res = _invoke_hook(payload, {"REASON_VALIDATOR_LOG_DIR": str(tmp_path)})
    assert res.returncode == 0
    # No log directory should be created for unrelated dispatches
    assert not (tmp_path / "testsess-unrelated").exists()


@pytest.mark.skipif(not HOOK.exists(), reason="hook not installed")
def test_hook_ignores_non_agent_tools(tmp_path):
    payload = {
        "session_id": "testsess-other-tool",
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/x"},
        "tool_response": "ok",
    }
    res = _invoke_hook(payload, {"REASON_VALIDATOR_LOG_DIR": str(tmp_path)})
    assert res.returncode == 0
    assert not (tmp_path / "testsess-other-tool").exists()


@pytest.mark.skipif(not HOOK.exists(), reason="hook not installed")
def test_hook_disabled_flag_short_circuits(tmp_path):
    report_text = (FIXTURES / "worker_empirical_bad_nocites.md").read_text()
    payload = {
        "session_id": "testsess-disabled",
        "tool_name": "Agent",
        "tool_input": {
            "description": "REASON worker: adversarial red-team",
            "subagent_type": "general-purpose",
            "prompt": "…",
        },
        "tool_response": report_text,
    }
    res = _invoke_hook(
        payload,
        {
            "REASON_VALIDATOR_LOG_DIR": str(tmp_path),
            "REASON_VALIDATOR_DISABLED": "1",
        },
    )
    assert res.returncode == 0
    assert res.stderr == ""  # no warning printed when disabled
    assert not (tmp_path / "testsess-disabled").exists()


@pytest.mark.skipif(not HOOK.exists(), reason="hook not installed")
def test_hook_handles_empty_stdin():
    """Hook must not crash on empty stdin (Claude Code edge case)."""
    env = {**os.environ, "REASON_VALIDATOR_LOG_DIR": "/tmp"}
    res = subprocess.run(
        [sys.executable, str(HOOK)],
        input="",
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert res.returncode == 0
