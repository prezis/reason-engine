#!/usr/bin/env python3
"""PostToolUse hook: validate REASON worker output at dispatch time.

Fires after every Agent tool call. If the agent's description matches a
REASON worker signature (e.g. "REASON worker: adversarial red-team"), we:

  1. Extract the worker role from the description.
  2. Read the agent's final output text from tool_response.
  3. Parse it with `reason.parser.parse_worker_report`.
  4. Run structural validation via `reason.validator.validate_report`.
  5. Write a JSONL record to ~/.reason-logs/<session_id>/validation.jsonl.
  6. Print WARN to stderr if the worker failed grounding.

WARN mode (current). The hook never blocks the tool chain — any failure
path returns exit code 0. Promotion to BLOCK happens after calibration
against ~20 live invocations confirms a low false-positive rate, per the
kopanie `post-change-validate.json` WARN→BLOCK precedent.

Environment variables (for testing / tuning):
  REASON_VALIDATOR_LOG_DIR   override output directory
  REASON_VALIDATOR_MODE      "warn" (default) | "block"  (BLOCK not yet wired)
  REASON_VALIDATOR_DISABLED  any non-empty value → no-op
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HOME = Path.home()

# Make the reason-engine package importable without installing it — the
# source tree lives next to this hook on this machine. For a foreign box
# you'd `pip install -e ~/ai/reason-engine/` and this bootstrap becomes a
# no-op.
_REASON_ENGINE = HOME / "ai" / "reason-engine"
if str(_REASON_ENGINE) not in sys.path and _REASON_ENGINE.is_dir():
    sys.path.insert(0, str(_REASON_ENGINE))

DEFAULT_LOG_DIR = HOME / ".reason-logs"
LOG_DIR = Path(
    os.environ.get("REASON_VALIDATOR_LOG_DIR", str(DEFAULT_LOG_DIR))
)

WORKER_DESCRIPTION_RE = re.compile(
    r"REASON\s+worker\s*[:\-–]\s*(?P<role>[a-z\-]+)", re.IGNORECASE
)

KNOWN_ROLES = {
    "adversarial", "skeptic", "synthesist", "domain-expert", "baseline",
}


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def _extract_role(description: str) -> str | None:
    if not description:
        return None
    m = WORKER_DESCRIPTION_RE.search(description)
    if not m:
        return None
    role = m.group("role").lower()
    # Dispatch descriptions like "adversarial red-team" — only the first
    # word should be the role. Strip any trailing modifier.
    role = role.split()[0] if " " in role else role
    # Known aliases seen in live runs
    if role == "domain":
        role = "domain-expert"
    if role.startswith("simple"):
        role = "baseline"
    if role.startswith("methodological"):
        role = "skeptic"
    if role.startswith("integrative"):
        role = "synthesist"
    if role.startswith("quant"):
        role = "domain-expert"
    if role not in KNOWN_ROLES:
        return None
    return role


def _extract_report_text(tool_response) -> str:
    """The tool_response shape varies across Claude Code versions. Accept
    a string, a dict with 'content' / 'output', or a list of blocks."""
    if tool_response is None:
        return ""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        for k in ("content", "output", "text", "response"):
            v = tool_response.get(k)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, list):
                parts = []
                for item in v:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                    elif isinstance(item, str):
                        parts.append(item)
                if parts:
                    return "\n".join(parts)
        # Last resort: stringify
        return json.dumps(tool_response)[:20000]
    if isinstance(tool_response, list):
        parts = []
        for item in tool_response:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(tool_response)[:20000]


def _write_record(session_id: str, record: dict) -> None:
    session_dir = LOG_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / "validation.jsonl"
    fd = os.open(
        str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
    )
    try:
        os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def main() -> int:
    if os.environ.get("REASON_VALIDATOR_DISABLED"):
        return 0

    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    if not raw:
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    tool = payload.get("tool_name", "")
    if tool != "Agent":
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    description = tool_input.get("description", "")
    role = _extract_role(description)
    if role is None:
        return 0  # not a REASON worker dispatch

    session_id = payload.get("session_id", "unknown")
    tool_response = (
        payload.get("tool_response")
        or payload.get("tool_result")
        or payload.get("output")
    )
    report_text = _extract_report_text(tool_response)

    try:
        from reason.parser import parse_worker_report
        from reason.validator import validate_report
    except Exception as e:
        # reason-engine not importable — log once and bail gracefully.
        _stderr(f"[reason-validator] import failed: {e}")
        return 0

    try:
        report = parse_worker_report(role, report_text)
        result = validate_report(report)
    except Exception as e:
        _stderr(f"[reason-validator] parse/validate failed: {e}")
        return 0

    record = {
        "ts": time.time(),
        "session_id": session_id,
        "role": role,
        "description": description,
        "tool_uses_count": result.tool_uses_count,
        "tool_less_by_design": result.tool_less_by_design,
        "citations_checked": result.citations_checked,
        "citations_valid": result.citations_valid,
        "grounding_score": result.grounding_score,
        "ok": result.ok,
        "violations": [
            {"kind": v.kind, "detail": v.detail, "citation_index": v.citation_index}
            for v in result.violations
        ],
        "mode": os.environ.get("REASON_VALIDATOR_MODE", "warn"),
    }

    try:
        _write_record(session_id, record)
    except Exception as e:
        _stderr(f"[reason-validator] log write failed: {e}")

    if not result.ok:
        kinds = ", ".join(sorted({v.kind for v in result.violations})) or "unknown"
        _stderr(
            f"[reason-validator WARN] {role}: FAIL ({kinds}) "
            f"tool_uses={result.tool_uses_count} "
            f"citations={result.citations_valid}/{result.citations_checked} "
            f"score={result.grounding_score:.2f}"
        )

    # WARN mode: never block the tool chain.
    return 0


if __name__ == "__main__":
    sys.exit(main())
