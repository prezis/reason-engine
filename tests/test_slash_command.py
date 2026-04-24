"""Contract tests for the /reason slash command orchestrator.

Guards against regressions in Stage 3 (judge) and Stage 4 (synthesis) that
would let low-grounding workers slip through with unmerited confidence
(paired with tests/test_worker_prompts.py which guards the worker side).
"""
import os
import pytest

SLASH_CMD_PATH = os.path.expanduser("~/.claude/commands/reason.md")


@pytest.fixture(scope="module")
def body() -> str:
    assert os.path.exists(SLASH_CMD_PATH), f"missing slash command: {SLASH_CMD_PATH}"
    return open(SLASH_CMD_PATH).read()


def test_has_frontmatter_allowed_tools(body: str):
    assert "allowed-tools:" in body, "missing allowed-tools frontmatter"
    assert "Agent" in body, "Agent must be allowed — workers dispatched as subagents"


def test_has_four_stages(body: str):
    for stage in ("Stage 1", "Stage 2", "Stage 3", "Stage 4"):
        assert stage in body, f"slash command missing {stage}"


def test_stage2_dispatches_five_roles(body: str):
    for role in ("adversarial", "skeptic", "synthesist", "domain-expert", "baseline"):
        assert role in body, f"Stage-2 dispatch list missing role: {role}"


def test_stage3_requires_grounding_check(body: str):
    """Stage 3 must inspect each worker's Tool-use summary and tag
    low-grounding reports before the judge scores them."""
    assert "Grounding check" in body, "Stage 3 missing the grounding-check gate"
    assert "Tool-use summary" in body, (
        "Stage 3 must reference the 'Tool-use summary' field that workers produce"
    )
    assert "low-grounding" in body, (
        "Stage 3 must tag ungrounded workers as 'low-grounding' for downstream "
        "confidence adjustment"
    )


def test_stage3_prefers_runtime_validator_over_self_report(body: str):
    """Stage 3 must treat ~/.reason-logs/<session>/validation.jsonl (written
    by the reason-validator.py hook) as authoritative, falling back to the
    prompt-level Tool-use summary only when the log is missing."""
    assert "validation.jsonl" in body, (
        "Stage 3 must read the hook's validation.jsonl — otherwise the "
        "runtime validator's authoritative verdict is ignored"
    )
    assert "authoritative" in body.lower(), (
        "Stage 3 must name the runtime validator as authoritative over "
        "the worker's self-reported Tool-use summary"
    )


def test_stage4_downweights_low_grounding(body: str):
    """Stage 4 must explicitly downweight claims supported only by
    low-grounding workers — otherwise the grounding tag is decorative."""
    assert "low-grounding" in body, "Stage 4 must reference low-grounding"
    assert "drops one confidence tier" in body or "drop confidence" in body, (
        "Stage 4 must specify the confidence-tier penalty for low-grounding claims"
    )


def test_stage4_has_grounding_audit_footer(body: str):
    """The final output must surface which workers were tagged low-grounding
    so the user can judge the synthesis."""
    assert "Grounding audit" in body, (
        "Stage 4 output must include a 'Grounding audit' footer listing "
        "low-grounding workers and how that affected the synthesis"
    )


def test_supports_debate_mode(body: str):
    assert "--mode=debate" in body, "slash command must support --mode=debate"
    assert "Debate-preset section" in body or "debate-preset" in body, (
        "debate-mode preset section missing"
    )


def test_references_rubric_judge_tool(body: str):
    assert "mcp__local-ai__local_rubric_judge" in body, (
        "Stage 3 must call the local rubric judge MCP tool"
    )
