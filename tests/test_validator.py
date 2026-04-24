"""Validator contract tests.

The validator applies role-aware grounding rules and filesystem checks to
a parsed `WorkerReport`. It catches:
  - empirical workers with zero tool uses
  - empirical workers with too few citations
  - citations pointing to nonexistent files (fabricated paths)
  - line ranges beyond the file's actual length
  - quoted snippets that don't appear in the file at the claimed range
"""
import os
import tempfile
import pytest

from reason.parser import parse_worker_report, Citation, WorkerReport
from reason.validator import (
    validate_report,
    ValidationResult,
    Violation,
    ROLE_THRESHOLDS,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


@pytest.fixture
def tmp_cite_file(tmp_path):
    """Write a fake file we can cite against."""
    p = tmp_path / "fake.md"
    p.write_text("line1\nline2\nline3 with keyword\nline4\nline5\n")
    return p


# ── role thresholds exist and make sense ─────────────────────────

def test_role_thresholds_defined_for_all_roles():
    for role in ("adversarial", "skeptic", "synthesist", "domain-expert", "baseline"):
        assert role in ROLE_THRESHOLDS


def test_domain_expert_threshold_stricter_than_others():
    """domain-expert prompt mandates tool_uses >= 3, others >= 1."""
    assert ROLE_THRESHOLDS["domain-expert"].min_tool_uses >= 3
    assert ROLE_THRESHOLDS["adversarial"].min_tool_uses >= 1


def test_baseline_threshold_is_exempt():
    th = ROLE_THRESHOLDS["baseline"]
    assert th.exempt is True


# ── happy paths ──────────────────────────────────────────────────

def test_valid_adversarial_passes():
    rep = parse_worker_report("adversarial", _load("worker_adversarial_ok.md"))
    # Our fixture cites files that may not all exist on THIS machine layout,
    # but the structural checks (tool_uses, citation count) must pass.
    res = validate_report(rep, search_roots=[])
    assert res.tool_uses_count >= 5
    assert res.citations_checked >= 2


def test_valid_baseline_passes_despite_zero_tool_uses():
    rep = parse_worker_report("baseline", _load("worker_baseline_ok.md"))
    res = validate_report(rep, search_roots=[])
    assert res.ok is True, f"baseline must pass; violations={res.violations}"
    assert res.tool_uses_count == 0


# ── failures: empirical worker with zero tool uses ───────────────

def test_empirical_nocites_report_fails_on_zero_tool_uses():
    rep = parse_worker_report("skeptic", _load("worker_empirical_bad_nocites.md"))
    res = validate_report(rep, search_roots=[])
    assert res.ok is False
    kinds = {v.kind for v in res.violations}
    assert "no_tool_uses" in kinds or "insufficient_tool_uses" in kinds


def test_empirical_nocites_report_fails_on_insufficient_citations():
    rep = parse_worker_report("skeptic", _load("worker_empirical_bad_nocites.md"))
    res = validate_report(rep, search_roots=[])
    kinds = {v.kind for v in res.violations}
    assert "insufficient_citations" in kinds


# ── filesystem checks ────────────────────────────────────────────

def test_path_not_found_is_flagged(tmp_path):
    """A citation to a nonexistent file fails with path_not_found."""
    rep = WorkerReport(
        role="adversarial",
        raw="",
        tool_uses_count=5,
        citations=[
            Citation(path="does-not-exist.md", line_start=1, line_end=5, quote="x"),
        ],
    )
    res = validate_report(rep, search_roots=[tmp_path])
    kinds = {v.kind for v in res.violations}
    assert "path_not_found" in kinds


def test_line_range_beyond_file_length_is_flagged(tmp_cite_file):
    """Line range past end of file fails with line_range_invalid."""
    rep = WorkerReport(
        role="adversarial",
        raw="",
        tool_uses_count=5,
        citations=[
            # file has 5 lines; asking for L99-L100 must fail
            Citation(
                path=tmp_cite_file.name,
                line_start=99,
                line_end=100,
                quote="nope",
            ),
        ],
    )
    res = validate_report(rep, search_roots=[tmp_cite_file.parent])
    kinds = {v.kind for v in res.violations}
    assert "line_range_invalid" in kinds


def test_quote_mismatch_is_flagged(tmp_cite_file):
    """Quote that isn't a substring of file[start:end] fails with quote_mismatch."""
    rep = WorkerReport(
        role="adversarial",
        raw="",
        tool_uses_count=5,
        citations=[
            Citation(
                path=tmp_cite_file.name,
                line_start=1,
                line_end=2,
                quote="this string is not in the file at all",
            ),
        ],
    )
    res = validate_report(rep, search_roots=[tmp_cite_file.parent])
    kinds = {v.kind for v in res.violations}
    assert "quote_mismatch" in kinds


def test_valid_citation_passes(tmp_cite_file):
    """Citation whose quote IS a substring of the file at the range passes."""
    rep = WorkerReport(
        role="adversarial",
        raw="",
        tool_uses_count=5,
        citations=[
            Citation(
                path=tmp_cite_file.name,
                line_start=3,
                line_end=3,
                quote="keyword",
            ),
            Citation(
                path=tmp_cite_file.name,
                line_start=1,
                line_end=5,
                quote="line4",
            ),
        ],
    )
    res = validate_report(rep, search_roots=[tmp_cite_file.parent])
    assert res.ok is True, f"violations: {res.violations}"
    assert res.citations_valid == 2


# ── fabricated fixture end-to-end ────────────────────────────────

def test_fabricated_report_fails(tmp_path):
    """The worker_empirical_bad_fabricated.md fixture cites paths that don't
    exist + line ranges past file length. Validator must reject."""
    rep = parse_worker_report(
        "synthesist", _load("worker_empirical_bad_fabricated.md")
    )
    res = validate_report(rep, search_roots=[tmp_path])  # empty search root
    assert res.ok is False
    # At least one path_not_found violation (both cited paths are fake)
    kinds = {v.kind for v in res.violations}
    assert "path_not_found" in kinds


# ── grounding score ─────────────────────────────────────────────

def test_grounding_score_is_1_0_for_valid_report(tmp_cite_file):
    rep = WorkerReport(
        role="adversarial",
        raw="",
        tool_uses_count=5,
        citations=[
            Citation(path=tmp_cite_file.name, line_start=3, line_end=3, quote="keyword"),
            Citation(path=tmp_cite_file.name, line_start=1, line_end=5, quote="line4"),
        ],
    )
    res = validate_report(rep, search_roots=[tmp_cite_file.parent])
    assert res.grounding_score == pytest.approx(1.0)


def test_grounding_score_is_0_for_all_bad_citations():
    rep = WorkerReport(
        role="adversarial",
        raw="",
        tool_uses_count=5,
        citations=[
            Citation(path="does-not-exist.md", line_start=1, line_end=5, quote="x"),
            Citation(path="also-gone.md", line_start=1, line_end=5, quote="y"),
        ],
    )
    res = validate_report(rep, search_roots=[])
    assert res.grounding_score == 0.0


# ── result structure ─────────────────────────────────────────────

def test_result_is_json_serializable():
    """The hook serializes results to JSONL — must be dataclass-friendly."""
    import json
    from dataclasses import asdict

    rep = parse_worker_report("baseline", _load("worker_baseline_ok.md"))
    res = validate_report(rep, search_roots=[])
    data = asdict(res)
    # Round-trip
    serialized = json.dumps(data)
    assert "role" in serialized
    assert "violations" in serialized
