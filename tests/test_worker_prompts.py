"""Worker-prompt contract tests.

Guards against the "0 tool uses" regression observed 2026-04-24: workers were
generating prose from training data instead of grounding in real files. The
tests below enforce an imperative tool-call contract on every empirical role.
"""
import os
import pytest

WORKERS_DIR = os.path.expanduser("~/.claude/commands/reason/workers")
REQUIRED_PLACEHOLDERS = ("{question}", "{abstract_question}")
REQUIRED_SECTIONS = ("## Role", "## Output format")
EXPECTED = ("adversarial", "skeptic", "synthesist", "domain-expert", "baseline")

# Workers that MUST ground their claims with tool calls. Baseline is excluded
# by design — its value is first-reaction intuition, not vault lookup.
EMPIRICAL_ROLES = ("adversarial", "skeptic", "synthesist", "domain-expert")

# Every empirical worker prompt must mention at least 2 of these tool names
# so the LLM has concrete invocation targets, not vague "use the vault".
TOOL_VOCABULARY = (
    "Grep", "Read", "Glob",
    "mcp__qmd__search", "mcp__qmd__vector_search", "mcp__qmd__deep_search",
    "mcp__local-ai__local_web_search",
)


def _read(role: str) -> str:
    path = os.path.join(WORKERS_DIR, f"{role}.md")
    return open(path).read()


@pytest.mark.parametrize("role", EXPECTED)
def test_worker_prompt_exists(role):
    path = os.path.join(WORKERS_DIR, f"{role}.md")
    assert os.path.exists(path), f"missing worker prompt: {path}"


@pytest.mark.parametrize("role", EXPECTED)
def test_worker_prompt_has_placeholders(role):
    body = _read(role)
    for ph in REQUIRED_PLACEHOLDERS:
        assert ph in body, f"{role}.md missing {ph}"


@pytest.mark.parametrize("role", EXPECTED)
def test_worker_prompt_has_sections(role):
    body = _read(role)
    for s in REQUIRED_SECTIONS:
        assert s in body, f"{role}.md missing section {s}"


@pytest.mark.parametrize("role", EMPIRICAL_ROLES)
def test_empirical_worker_has_mandatory_prework(role):
    """Every empirical worker must have a MANDATORY PRE-WORK block that commands
    tool usage — the cure for the 0-tool-uses regression."""
    body = _read(role)
    assert "## MANDATORY PRE-WORK" in body, (
        f"{role}.md lacks a MANDATORY PRE-WORK section — workers will default "
        f"to prose-from-memory with 0 tool uses"
    )


@pytest.mark.parametrize("role", EMPIRICAL_ROLES)
def test_empirical_worker_names_concrete_tools(role):
    """Saying 'use the vault' isn't enough — the prompt must name specific
    tools the worker can invoke, or the LLM won't call any."""
    body = _read(role)
    hits = [t for t in TOOL_VOCABULARY if t in body]
    assert len(hits) >= 2, (
        f"{role}.md mentions only {len(hits)} concrete tool name(s) "
        f"{hits} — need at least 2 from {TOOL_VOCABULARY}"
    )


@pytest.mark.parametrize("role", EMPIRICAL_ROLES)
def test_empirical_worker_requires_line_citations(role):
    """Force verifiable citation format (path:Lstart-Lend > "quote") instead
    of the old [[wikilink]] pattern, which can be invented without reading."""
    body = _read(role)
    assert ":Lstart-Lend" in body or ":L23-L45" in body, (
        f"{role}.md must instruct workers to cite with line ranges "
        f"(path:Lstart-Lend > \"quote\") so citations are verifiable"
    )


@pytest.mark.parametrize("role", EMPIRICAL_ROLES)
def test_empirical_worker_has_tool_use_summary(role):
    """Output format must require a Tool-use summary so the judge can see
    which workers grounded their claims and which fabricated from memory."""
    body = _read(role)
    assert "Tool-use summary" in body, (
        f"{role}.md output format must include a 'Tool-use summary' field "
        f"so the judge can detect low-grounding outputs"
    )


def test_baseline_is_tool_less_by_design():
    """The baseline worker must EXPLICITLY declare itself tool-less so LLMs
    treat its 0-tool-uses as intentional, not as a bug."""
    body = _read("baseline")
    assert "TOOL-LESS BY DESIGN" in body, (
        "baseline.md must explicitly state 'TOOL-LESS BY DESIGN' so its "
        "distinctive YAGNI voice isn't confused with a grounding failure"
    )
