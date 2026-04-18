# tests/test_freshness.py
"""Freshness schema + parser — pure logic, no I/O."""
import pytest
from reason.freshness import (
    parse_frontmatter, validate_schema, is_protected_field,
    PROTECTED_FIELDS, APPENDABLE_FIELDS, FreshnessError,
)


def test_parses_minimal_frontmatter():
    body = """---
kind: article
mutability: living
---
# Doc"""
    fm, rest = parse_frontmatter(body)
    assert fm["kind"] == "article"
    assert rest.startswith("# Doc")


def test_parses_additive_fields():
    body = """---
kind: article
session_feedback:
  - { session: abc, ts: 2026-04-18T00:00Z, vote: cited-accurate }
last_verified_entries:
  - { session: abc, ts: 2026-04-18T00:00Z, action: cited-accurate }
---
"""
    fm, _ = parse_frontmatter(body)
    assert len(fm["session_feedback"]) == 1
    assert fm["session_feedback"][0]["session"] == "abc"


def test_protected_fields_enumerated():
    assert "status" in PROTECTED_FIELDS
    assert "supersedes" in PROTECTED_FIELDS
    assert "superseded_by" in PROTECTED_FIELDS
    assert "session_feedback" in APPENDABLE_FIELDS
    assert "last_verified_entries" in APPENDABLE_FIELDS
    assert "reference_count" in APPENDABLE_FIELDS


def test_is_protected_field():
    assert is_protected_field("status")
    assert is_protected_field("superseded_by")
    assert not is_protected_field("session_feedback")
    assert not is_protected_field("kind")


def test_validate_schema_accepts_valid():
    fm = {
        "kind": "article",
        "mutability": "living",
        "session_feedback": [
            {"session": "abc", "ts": "2026-04-18T00:00Z", "vote": "cited-accurate"}
        ],
    }
    validate_schema(fm)  # does not raise


def test_validate_schema_rejects_bad_vote():
    fm = {"kind": "article", "session_feedback": [{"session": "abc", "ts": "x", "vote": "BOGUS"}]}
    with pytest.raises(FreshnessError):
        validate_schema(fm)


def test_validate_schema_rejects_oversized_feedback():
    big = [{"session": "s", "ts": "t", "vote": "cited-accurate", "note": "x"*600}
           for _ in range(200)]
    fm = {"kind": "article", "session_feedback": big}
    with pytest.raises(FreshnessError, match="bounded"):
        validate_schema(fm)
