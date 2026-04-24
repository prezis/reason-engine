#!/usr/bin/env python3
"""UserPromptSubmit hook — detects REASON trigger phrases, injects context.

Contract (Claude Code hooks):
- stdin: JSON with {prompt, session_id, ...}
- stdout: hook-protocol JSON or empty (pass-through)
- Exit 0 always — never block the tool chain.
"""
import html
import json
import sys
import os

# Add reason-engine package to path
sys.path.insert(0, os.path.expanduser("~/ai/reason-engine"))

try:
    from reason.trigger import detect_trigger
except Exception:
    print("", end="")
    sys.exit(0)


TRIGGER_EVENTS_LOG = os.path.expanduser("~/.reason-logs/trigger-events.jsonl")


def _log_trigger_event(event: dict) -> None:
    """Append a trigger detection event to ~/.reason-logs/trigger-events.jsonl.

    Spec §1 (UserPromptSubmit hook): 'Logs every invocation to
    ~/.reason-logs/trigger-events.jsonl for trigger-accuracy measurement.'
    Best-effort — never blocks or errors the hook.
    """
    try:
        os.makedirs(os.path.dirname(TRIGGER_EVENTS_LOG), exist_ok=True)
        fd = os.open(TRIGGER_EVENTS_LOG,
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass  # observability must not break the hook


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw:
            return 0
        payload = json.loads(raw)
        prompt = payload.get("prompt", "") or ""
        session_id = payload.get("session_id", "unknown")
        r = detect_trigger(prompt)

        # Log EVERY invocation (matched or not) so we can measure
        # true-positive / false-positive / false-negative rates over time.
        import time
        _log_trigger_event({
            "ts": time.time(),
            "session_id": session_id,
            "matched": r is not None,
            "mode": r.mode if r else None,
            "prompt_len": len(prompt),
            "prompt_prefix": prompt[:80],  # just a fingerprint, not full content
        })

        if r is None:
            return 0
        safe_mode = html.escape(str(r.mode), quote=True)
        safe_prompt = html.escape(r.stripped)
        marker = (
            f"\n\n<REASON_TRIGGER mode=\"{safe_mode}\">\n"
            f"The user's message contains a REASON trigger phrase. "
            f"Invoke the /reason slash command with the following question "
            f"(mode={safe_mode}):\n\n{safe_prompt}\n</REASON_TRIGGER>"
        )
        out = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": marker,
            }
        }
        print(json.dumps(out))
    except Exception:
        print("", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
