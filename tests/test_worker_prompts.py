"""Every worker prompt must have required sections + placeholders."""
import os
import pytest

WORKERS_DIR = os.path.expanduser("~/.claude/commands/reason/workers")
REQUIRED_PLACEHOLDERS = ("{question}", "{abstract_question}")
REQUIRED_SECTIONS = ("## Role", "## Output format")
EXPECTED = ("adversarial", "skeptic", "synthesist", "domain-expert", "baseline")


@pytest.mark.parametrize("role", EXPECTED)
def test_worker_prompt_exists(role):
    path = os.path.join(WORKERS_DIR, f"{role}.md")
    assert os.path.exists(path), f"missing worker prompt: {path}"


@pytest.mark.parametrize("role", EXPECTED)
def test_worker_prompt_has_placeholders(role):
    path = os.path.join(WORKERS_DIR, f"{role}.md")
    body = open(path).read()
    for ph in REQUIRED_PLACEHOLDERS:
        assert ph in body, f"{role}.md missing {ph}"


@pytest.mark.parametrize("role", EXPECTED)
def test_worker_prompt_has_sections(role):
    path = os.path.join(WORKERS_DIR, f"{role}.md")
    body = open(path).read()
    for s in REQUIRED_SECTIONS:
        assert s in body, f"{role}.md missing section {s}"
