"""Parse a worker report's raw markdown into a structured `WorkerReport`.

Pure — no I/O, no filesystem access. Extraction only.

The downstream `reason.validator` module takes the parsed report and runs
filesystem + semantic checks against the extracted citations.

Grounding contract the parser knows about:
  - Every empirical worker report should contain a `Tool-use summary` section.
  - Citations in the body use the form `path/file.ext:Lstart-Lend > "quote"`
    (backticks optional; path extensions extensible).
  - The baseline role declares itself `tool-less by design` — any report whose
    Tool-use summary contains that phrase is tagged accordingly so the
    validator does not flag it as a grounding failure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

KNOWN_ROLES = frozenset({
    "adversarial",
    "skeptic",
    "synthesist",
    "domain-expert",
    "baseline",
})

EMPIRICAL_ROLES = frozenset(KNOWN_ROLES - {"baseline"})

# Matches:  path/file.ext:Lstart-Lend > "quote"   (backticks optional)
# Extensions kept narrow; expand when a real worker cites something else.
_CITATION_RE = re.compile(
    r"`?"
    r"(?P<path>[A-Za-z0-9_\-./~]+\.(?:md|py|json|jsonl|yaml|yml|toml|sh|txt))"
    r":L(?P<start>\d+)-L(?P<end>\d+)"
    r"\s*>\s*"
    r"\"(?P<quote>[^\"]+)\""
    r"`?"
)

# Header forms accepted for the Tool-use summary section:
#   ## Tool-use summary
#   **Tool-use summary:** …
#   - **Tool-use summary:** …
_TOOL_USE_HEADER_RE = re.compile(
    r"^(?:#{1,6}\s+Tool-use\s+summary|\s*-?\s*\*\*Tool-use\s+summary:?\*\*)",
    re.IGNORECASE | re.MULTILINE,
)

_TOOL_LESS_MARKER_RE = re.compile(r"tool[-\s]*less\s+by\s+design", re.IGNORECASE)

# Any hyphen or asterisk bullet — used for counting tool calls in the summary.
_BULLET_RE = re.compile(r"^\s*[-*]\s+\S", re.MULTILINE)


@dataclass(frozen=True)
class Citation:
    path: str
    line_start: int
    line_end: int
    quote: str


@dataclass
class WorkerReport:
    role: str
    raw: str
    tool_uses_count: int = 0
    tool_less_by_design: bool = False
    citations: list[Citation] = field(default_factory=list)


def _extract_tool_use_block(markdown: str) -> str | None:
    """Return the text between the Tool-use summary header and the next
    header / section break, or None if the header isn't present."""
    m = _TOOL_USE_HEADER_RE.search(markdown)
    if not m:
        return None
    start = m.end()
    # Stop at the next top-level heading (## or beyond) or a bold line that
    # looks like another section label (e.g. `**Confidence`).
    tail = markdown[start:]
    stop_re = re.compile(
        r"(?:\n\s*#{1,6}\s+|\n\s*\*\*(?!Tool-use)[A-Z][^\n*]{2,40}:?\*\*)",
    )
    m_stop = stop_re.search(tail)
    block = tail if m_stop is None else tail[: m_stop.start()]
    return block


def _count_tool_uses(block: str) -> int:
    """Count bulleted tool-call lines. Robust to the 'tool-less' marker —
    caller decides what to do with the zero."""
    if _TOOL_LESS_MARKER_RE.search(block):
        return 0
    return len(_BULLET_RE.findall(block))


def _extract_citations(markdown: str) -> list[Citation]:
    out: list[Citation] = []
    seen: set[tuple[str, int, int, str]] = set()
    for m in _CITATION_RE.finditer(markdown):
        start = int(m.group("start"))
        end = int(m.group("end"))
        if end < start:
            continue  # malformed range — skip, validator won't see it
        key = (m.group("path"), start, end, m.group("quote"))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Citation(
                path=m.group("path"),
                line_start=start,
                line_end=end,
                quote=m.group("quote"),
            )
        )
    return out


def parse_worker_report(role: str, markdown: str) -> WorkerReport:
    """Parse a worker's raw markdown report.

    Args:
        role: One of the 5 known roles (`adversarial`, `skeptic`, `synthesist`,
            `domain-expert`, `baseline`).
        markdown: The worker's final message text.

    Returns:
        A `WorkerReport` with tool-use count, tool-less-by-design flag,
        and the list of citations extracted from the body.

    Raises:
        ValueError: If `role` is not a known role.
    """
    if role not in KNOWN_ROLES:
        raise ValueError(f"unknown role: {role!r} (known: {sorted(KNOWN_ROLES)})")

    block = _extract_tool_use_block(markdown)
    if block is None:
        tool_uses_count = 0
        tool_less_by_design = False
    else:
        is_baseline_declaration = (
            role == "baseline" and _TOOL_LESS_MARKER_RE.search(block) is not None
        )
        tool_uses_count = _count_tool_uses(block)
        tool_less_by_design = is_baseline_declaration

    citations = _extract_citations(markdown)

    return WorkerReport(
        role=role,
        raw=markdown,
        tool_uses_count=tool_uses_count,
        tool_less_by_design=tool_less_by_design,
        citations=citations,
    )
