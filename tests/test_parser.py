"""Parser contract tests.

The parser converts a worker's raw markdown report into a structured
WorkerReport (role, tool_uses_count, citations). It is pure — no I/O,
no filesystem access. Downstream validators handle filesystem checks.
"""
import os
import pytest

from reason.parser import (
    WorkerReport,
    Citation,
    parse_worker_report,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


# ── role + tool-use counting ──────────────────────────────────────

def test_parse_adversarial_ok_counts_tool_uses():
    r = parse_worker_report("adversarial", _load("worker_adversarial_ok.md"))
    assert isinstance(r, WorkerReport)
    assert r.role == "adversarial"
    # fixture has 6 hyphen-prefixed bullets under Tool-use summary
    assert r.tool_uses_count >= 5, f"expected >=5, got {r.tool_uses_count}"


def test_parse_baseline_ok_detects_tool_less_by_design():
    r = parse_worker_report("baseline", _load("worker_baseline_ok.md"))
    assert r.role == "baseline"
    assert r.tool_uses_count == 0
    assert r.tool_less_by_design is True


def test_parse_empirical_bad_nocites_zero_tool_uses():
    r = parse_worker_report("skeptic", _load("worker_empirical_bad_nocites.md"))
    assert r.role == "skeptic"
    assert r.tool_uses_count == 0
    # skeptic is empirical, so tool_less_by_design must be False even if count is 0
    assert r.tool_less_by_design is False


# ── citation extraction ──────────────────────────────────────────

def test_parse_adversarial_extracts_citations():
    r = parse_worker_report("adversarial", _load("worker_adversarial_ok.md"))
    assert len(r.citations) >= 2, f"expected >=2 citations, got {len(r.citations)}"
    # Each citation must have path + line-range + quote
    for c in r.citations:
        assert isinstance(c, Citation)
        assert c.path  # non-empty
        assert c.line_start >= 1
        assert c.line_end >= c.line_start
        assert c.quote  # non-empty


def test_parse_citation_values_are_specific():
    """Confirm the parser extracts exact path / line-range / quote — not a regex false positive."""
    r = parse_worker_report("adversarial", _load("worker_adversarial_ok.md"))
    # Find the defeating-lussers-law citation at L25
    lussers = [c for c in r.citations if "defeating-lussers-law" in c.path and c.line_start == 25]
    assert len(lussers) >= 1, "expected the L25 Lusser citation"
    assert "All 5 are needed" in lussers[0].quote


def test_parse_bad_nocites_has_no_citations():
    r = parse_worker_report("skeptic", _load("worker_empirical_bad_nocites.md"))
    assert r.citations == []


def test_parse_bad_fabricated_extracts_citations_without_filesystem_check():
    """Parser must extract citations even if they point to nonexistent files —
    that's the validator's job to reject later."""
    r = parse_worker_report("synthesist", _load("worker_empirical_bad_fabricated.md"))
    assert len(r.citations) == 2
    paths = {c.path for c in r.citations}
    assert "global-graph/patterns/does-not-exist.md" in paths


# ── edge cases ──────────────────────────────────────────────────

def test_parse_rejects_unknown_role():
    with pytest.raises(ValueError, match="unknown role"):
        parse_worker_report("not-a-role", "# some report")


def test_parse_empty_body_still_returns_report():
    """Empty worker output is valid-parseable with zero counts — downstream
    validator decides it's a failure."""
    r = parse_worker_report("adversarial", "")
    assert r.tool_uses_count == 0
    assert r.citations == []
    assert r.tool_less_by_design is False


def test_parse_citation_range_can_be_single_line():
    """Format `path:L25-L25 > "quote"` — same start and end."""
    md = '''# Report
## Tool-use summary
- Read file

A citation: `some/file.md:L25-L25 > "a quote"`.
'''
    r = parse_worker_report("adversarial", md)
    assert len(r.citations) == 1
    assert r.citations[0].line_start == 25
    assert r.citations[0].line_end == 25
