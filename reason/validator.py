"""Structural validator for REASON worker reports.

Given a parsed `WorkerReport`, apply role-aware grounding rules and
filesystem checks:

  - Empirical workers (adversarial, skeptic, synthesist, domain-expert) MUST
    have at least N tool uses and M citations. Thresholds live in
    `ROLE_THRESHOLDS`.
  - Baseline is exempt (`tool-less by design`). Validator accepts any count.
  - For every citation: resolve the path against a list of search roots,
    check the line range is within the file, and check the quote is a
    substring of the file text at the claimed range.

This is the Layer-1 deterministic gate (per
`~/ai/global-graph/patterns/defeating-lussers-law.md`). It catches
STRUCTURAL bypass — fabricated paths, invented line ranges, quotes that
don't appear in the file. It does NOT catch SEMANTIC bypass (quote exists
but doesn't support the claim) — that's the Layer-5 job, implemented in
`reason.semantic_sampler`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from reason.parser import WorkerReport, Citation, EMPIRICAL_ROLES


@dataclass(frozen=True)
class RoleThreshold:
    role: str
    min_tool_uses: int
    min_citations: int
    exempt: bool = False


ROLE_THRESHOLDS: dict[str, RoleThreshold] = {
    "adversarial": RoleThreshold("adversarial", min_tool_uses=1, min_citations=2),
    "skeptic":     RoleThreshold("skeptic",     min_tool_uses=1, min_citations=2),
    "synthesist":  RoleThreshold("synthesist",  min_tool_uses=1, min_citations=2),
    # domain-expert prompt mandates tool-use >= 3 and >= 3 citations
    "domain-expert": RoleThreshold(
        "domain-expert", min_tool_uses=3, min_citations=3,
    ),
    "baseline":    RoleThreshold(
        "baseline", min_tool_uses=0, min_citations=0, exempt=True,
    ),
}


@dataclass(frozen=True)
class Violation:
    kind: str
    detail: str
    citation_index: int = -1  # -1 = report-level, else index into citations list


@dataclass
class ValidationResult:
    role: str
    ok: bool
    tool_uses_count: int
    tool_less_by_design: bool
    citations_checked: int
    citations_valid: int
    grounding_score: float  # 0.0..1.0, ratio of valid citations
    violations: list[Violation] = field(default_factory=list)


def _default_search_roots() -> list[Path]:
    home = Path.home()
    return [home / "ai", home]


def _resolve_citation_path(
    path_str: str, search_roots: list[Path]
) -> Path | None:
    """Return an existing absolute Path or None. Tries:
      1. Path as-is (absolute or relative to CWD).
      2. Each search root joined with path_str.
    """
    candidate = Path(path_str).expanduser()
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    if candidate.is_file():
        return candidate.resolve()
    for root in search_roots:
        joined = (root / path_str).expanduser()
        if joined.is_file():
            return joined.resolve()
    return None


def _check_citation(
    cit: Citation, index: int, search_roots: list[Path]
) -> list[Violation]:
    """Return a list of violations for a single citation (empty = valid)."""
    resolved = _resolve_citation_path(cit.path, search_roots)
    if resolved is None:
        return [
            Violation(
                kind="path_not_found",
                detail=f"{cit.path!r} not found under search roots",
                citation_index=index,
            )
        ]

    try:
        text = resolved.read_text(errors="replace")
    except OSError as e:
        return [
            Violation(
                kind="read_error",
                detail=f"{cit.path}: {e}",
                citation_index=index,
            )
        ]

    lines = text.splitlines()
    n = len(lines)
    if cit.line_start < 1 or cit.line_end > n or cit.line_start > cit.line_end:
        return [
            Violation(
                kind="line_range_invalid",
                detail=(
                    f"{cit.path}: range L{cit.line_start}-L{cit.line_end} "
                    f"outside file length {n}"
                ),
                citation_index=index,
            )
        ]

    # Quote substring check: allow the quote to appear anywhere inside the
    # cited line range (not strictly at line-start) — people paraphrase line
    # breaks. Whitespace is normalized for robustness.
    window = "\n".join(lines[cit.line_start - 1 : cit.line_end])
    normalized_window = " ".join(window.split())
    normalized_quote = " ".join(cit.quote.split())
    if normalized_quote not in normalized_window:
        return [
            Violation(
                kind="quote_mismatch",
                detail=(
                    f"{cit.path}:L{cit.line_start}-L{cit.line_end}: "
                    f"quote {cit.quote!r} not found in cited range"
                ),
                citation_index=index,
            )
        ]

    return []


def validate_report(
    report: WorkerReport,
    search_roots: list[Path] | None = None,
) -> ValidationResult:
    """Validate a parsed worker report.

    Args:
        report: parsed `WorkerReport`.
        search_roots: directories to resolve relative citation paths against.
            Defaults to `[~/ai, ~]` if None. Pass an empty list to force
            absolute-path-only resolution (useful for tests).

    Returns:
        `ValidationResult` with an aggregate `ok` flag, a `grounding_score`
        in [0, 1], and a list of `Violation`s.
    """
    if search_roots is None:
        search_roots = _default_search_roots()

    th = ROLE_THRESHOLDS.get(report.role)
    if th is None:
        # Parser would have rejected this, but belt-and-braces.
        return ValidationResult(
            role=report.role,
            ok=False,
            tool_uses_count=report.tool_uses_count,
            tool_less_by_design=report.tool_less_by_design,
            citations_checked=0,
            citations_valid=0,
            grounding_score=0.0,
            violations=[
                Violation(
                    kind="unknown_role",
                    detail=f"role {report.role!r} has no threshold",
                )
            ],
        )

    violations: list[Violation] = []

    # Report-level checks (skip if exempt).
    if not th.exempt:
        if report.tool_uses_count == 0:
            violations.append(
                Violation(
                    kind="no_tool_uses",
                    detail=(
                        f"{report.role}: 0 tool uses — empirical workers must "
                        f"invoke >= {th.min_tool_uses}"
                    ),
                )
            )
        elif report.tool_uses_count < th.min_tool_uses:
            violations.append(
                Violation(
                    kind="insufficient_tool_uses",
                    detail=(
                        f"{report.role}: {report.tool_uses_count} tool uses "
                        f"< threshold {th.min_tool_uses}"
                    ),
                )
            )

        if len(report.citations) < th.min_citations:
            violations.append(
                Violation(
                    kind="insufficient_citations",
                    detail=(
                        f"{report.role}: {len(report.citations)} citations "
                        f"< threshold {th.min_citations}"
                    ),
                )
            )

    # Per-citation filesystem checks.
    citations_valid = 0
    for idx, cit in enumerate(report.citations):
        cit_violations = _check_citation(cit, idx, search_roots)
        if cit_violations:
            violations.extend(cit_violations)
        else:
            citations_valid += 1

    citations_checked = len(report.citations)
    grounding_score = (
        citations_valid / citations_checked if citations_checked else 0.0
    )
    # Baseline has 0 checked citations → 0/0 → treat as 1.0 (exempt)
    if th.exempt and citations_checked == 0:
        grounding_score = 1.0

    ok = len(violations) == 0
    return ValidationResult(
        role=report.role,
        ok=ok,
        tool_uses_count=report.tool_uses_count,
        tool_less_by_design=report.tool_less_by_design,
        citations_checked=citations_checked,
        citations_valid=citations_valid,
        grounding_score=grounding_score,
        violations=violations,
    )


# ── CLI entry point (for the hook shim) ──────────────────────────

def _cli(argv: list[str]) -> int:
    """Usage: python -m reason.validator <role> <report_path> [--json]

    Exits 0 if the report passes, 1 if it fails.
    """
    import json
    import sys

    from reason.parser import parse_worker_report

    if len(argv) < 2:
        print(
            "usage: python -m reason.validator <role> <report_path> [--json]",
            file=sys.stderr,
        )
        return 2

    role, report_path, *rest = argv
    want_json = "--json" in rest

    with open(os.path.expanduser(report_path)) as f:
        markdown = f.read()

    report = parse_worker_report(role, markdown)
    result = validate_report(report)

    if want_json:
        from dataclasses import asdict
        print(json.dumps(asdict(result), ensure_ascii=False))
    else:
        status = "OK" if result.ok else "FAIL"
        print(f"[{status}] {role} — tool_uses={result.tool_uses_count} "
              f"citations={result.citations_valid}/{result.citations_checked} "
              f"score={result.grounding_score:.2f}")
        for v in result.violations:
            print(f"  - {v.kind}: {v.detail}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
