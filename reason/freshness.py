# reason/freshness.py
"""Freshness schema + frontmatter parser. Pure logic."""
from __future__ import annotations
import re
from typing import Any

try:
    import yaml
except ImportError:
    import sys
    sys.stderr.write("pyyaml required: pip install pyyaml\n")
    raise

PROTECTED_FIELDS = frozenset({"status", "supersedes", "superseded_by"})
APPENDABLE_FIELDS = frozenset({"session_feedback", "last_verified_entries", "reference_count"})
VALID_VOTES = frozenset({"cited-accurate", "seems-stale", "cited-but-tentative", "spot-checked"})
VALID_ACTIONS = frozenset({"cited-accurate", "spot-checked", "deep-verified"})
VALID_STATUSES = frozenset({"current", "deprecated", "superseded", "draft"})

MAX_FEEDBACK_ENTRIES = 50
MAX_NOTE_CHARS = 400
MAX_VERIFIED_ENTRIES = 50


class FreshnessError(ValueError):
    """Raised when frontmatter violates schema or authority rules."""


_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)", re.DOTALL)


def parse_frontmatter(body: str) -> tuple[dict[str, Any], str]:
    """Split a markdown doc into (frontmatter_dict, body_rest).

    Returns ({}, body) if no frontmatter present.
    """
    m = _FM_RE.match(body)
    if not m:
        return {}, body
    fm_raw, rest = m.group(1), m.group(2)
    fm = yaml.safe_load(fm_raw) or {}
    if not isinstance(fm, dict):
        raise FreshnessError("frontmatter is not a mapping")
    return fm, rest


def is_protected_field(name: str) -> bool:
    return name in PROTECTED_FIELDS


def validate_schema(fm: dict[str, Any]) -> None:
    """Raise FreshnessError on violation. Silent on pass."""
    st = fm.get("status")
    if st is not None and st not in VALID_STATUSES:
        raise FreshnessError(f"invalid status: {st!r}")

    fb = fm.get("session_feedback")
    if fb is not None:
        if not isinstance(fb, list):
            raise FreshnessError("session_feedback must be a list")
        if len(fb) > MAX_FEEDBACK_ENTRIES:
            raise FreshnessError(
                f"session_feedback bounded at {MAX_FEEDBACK_ENTRIES} (got {len(fb)})"
            )
        for i, e in enumerate(fb):
            if not isinstance(e, dict):
                raise FreshnessError(f"session_feedback[{i}] not a mapping")
            for req in ("session", "ts", "vote"):
                if req not in e:
                    raise FreshnessError(f"session_feedback[{i}] missing {req!r}")
            if e["vote"] not in VALID_VOTES:
                raise FreshnessError(
                    f"session_feedback[{i}].vote {e['vote']!r} not in {sorted(VALID_VOTES)}"
                )
            note = e.get("note", "") or ""
            if len(note) > MAX_NOTE_CHARS:
                raise FreshnessError(
                    f"session_feedback[{i}].note exceeds {MAX_NOTE_CHARS} chars"
                )

    lve = fm.get("last_verified_entries")
    if lve is not None:
        if not isinstance(lve, list):
            raise FreshnessError("last_verified_entries must be a list")
        if len(lve) > MAX_VERIFIED_ENTRIES:
            raise FreshnessError(
                f"last_verified_entries bounded at {MAX_VERIFIED_ENTRIES}"
            )
        for i, e in enumerate(lve):
            if not isinstance(e, dict):
                raise FreshnessError(f"last_verified_entries[{i}] not a mapping")
            for req in ("session", "ts", "action"):
                if req not in e:
                    raise FreshnessError(f"last_verified_entries[{i}] missing {req!r}")
            if e["action"] not in VALID_ACTIONS:
                raise FreshnessError(
                    f"last_verified_entries[{i}].action {e['action']!r} "
                    f"not in {sorted(VALID_ACTIONS)}"
                )

    rc = fm.get("reference_count")
    if rc is not None:
        if not isinstance(rc, int) or rc < 0:
            raise FreshnessError(f"reference_count must be non-neg int (got {rc!r})")
