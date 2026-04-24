"""Judge contract tests — prompt shape + response parsing.

Real Ollama calls are stubbed via monkey-patching httpx.post so tests run
offline and deterministically.
"""
import json
from dataclasses import asdict

import pytest

from reason.judge import (
    CRITERIA,
    JudgeResult,
    _build_prompt,
    _extract_json_text,
    _fallback_result,
    rubric_judge_sync,
)


SAMPLE_REPORTS = [
    {"role": "adversarial", "report": "Attack on premise X."},
    {"role": "baseline",    "report": "Just use A."},
]


# ── pure helpers ─────────────────────────────────────────────────

def test_build_prompt_includes_all_criteria():
    p = _build_prompt("q", "aq", SAMPLE_REPORTS)
    for c in CRITERIA:
        assert c in p


def test_build_prompt_includes_all_worker_reports():
    p = _build_prompt("q", "aq", SAMPLE_REPORTS)
    for w in SAMPLE_REPORTS:
        assert w["role"] in p
        assert w["report"] in p


def test_build_prompt_includes_step_back():
    p = _build_prompt("QUESTION1", "ABSTRACT2", SAMPLE_REPORTS)
    assert "QUESTION1" in p
    assert "ABSTRACT2" in p


def test_extract_json_prefers_response_field():
    assert _extract_json_text({"response": "A", "thinking": "B"}) == "A"


def test_extract_json_falls_back_to_thinking_when_response_empty():
    assert _extract_json_text({"response": "", "thinking": "B"}) == "B"


def test_extract_json_empty_when_both_empty():
    assert _extract_json_text({}) == ""
    assert _extract_json_text({"response": "", "thinking": ""}) == ""


def test_fallback_result_has_all_criteria_default_3():
    r = _fallback_result(SAMPLE_REPORTS, "bad output")
    assert r.degraded is True
    for w in SAMPLE_REPORTS:
        for c in CRITERIA:
            assert r.scores[w["role"]][c] == 3
        assert "rationale" in r.scores[w["role"]]
    assert r.ranking == ["adversarial", "baseline"]


# ── rubric_judge_sync with stubbed httpx ────────────────────────

def _fake_response(payload_dict):
    class R:
        def raise_for_status(self):
            return None

        def json(self):
            return payload_dict
    return R()


def test_rubric_judge_sync_parses_clean_response(monkeypatch):
    fake_output = json.dumps({
        "scores": {
            "adversarial": {
                "correctness": 4, "evidence_quality": 5,
                "logical_soundness": 4, "completeness": 4,
                "cites_or_synthesizes": 5, "rationale": "strong",
            },
            "baseline": {
                "correctness": 5, "evidence_quality": 3,
                "logical_soundness": 5, "completeness": 4,
                "cites_or_synthesizes": 2, "rationale": "dumb-simple",
            },
        },
        "ranking": ["adversarial", "baseline"],
    })

    def fake_post(url, json=None, timeout=None):
        return _fake_response({"response": fake_output})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    result = rubric_judge_sync("q", "aq", SAMPLE_REPORTS)
    assert result.degraded is False
    assert result.scores["adversarial"]["correctness"] == 4
    assert result.ranking == ["adversarial", "baseline"]


def test_rubric_judge_sync_clamps_out_of_range_scores(monkeypatch):
    """Judge output of 7 or 0 must clamp to [1,5]."""
    fake_output = json.dumps({
        "scores": {
            "adversarial": {
                "correctness": 7, "evidence_quality": 0,
                "logical_soundness": 4, "completeness": 4,
                "cites_or_synthesizes": -2, "rationale": "malformed",
            },
            "baseline": {
                "correctness": 5, "evidence_quality": 3,
                "logical_soundness": 5, "completeness": 4,
                "cites_or_synthesizes": 2, "rationale": "ok",
            },
        },
        "ranking": ["adversarial", "baseline"],
    })

    def fake_post(url, json=None, timeout=None):
        return _fake_response({"response": fake_output})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    result = rubric_judge_sync("q", "aq", SAMPLE_REPORTS)
    s = result.scores["adversarial"]
    assert s["correctness"] == 5  # clamped from 7
    assert s["evidence_quality"] == 1  # clamped from 0
    assert s["cites_or_synthesizes"] == 1  # clamped from -2


def test_rubric_judge_sync_falls_back_on_malformed_json(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _fake_response({"response": "not json at all"})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    result = rubric_judge_sync("q", "aq", SAMPLE_REPORTS)
    assert result.degraded is True
    # All workers get default 3
    for w in SAMPLE_REPORTS:
        for c in CRITERIA:
            assert result.scores[w["role"]][c] == 3


def test_rubric_judge_sync_falls_back_on_ollama_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise ConnectionError("ollama down")

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    result = rubric_judge_sync("q", "aq", SAMPLE_REPORTS)
    assert result.degraded is True
    assert "ollama down" in (result.raw or "")


def test_rubric_judge_sync_passes_think_false(monkeypatch):
    """Regression guard for the qwen3.x silent-thinking bug documented in
    prezis/local-ai-mcp/docs/qwen-thinking-mode.md."""
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return _fake_response({"response": '{"scores": {}, "ranking": []}'})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    rubric_judge_sync("q", "aq", SAMPLE_REPORTS)
    assert captured["body"]["think"] is False, (
        "judge must pass think=False or qwen3.x strands its JSON in the "
        "thinking field; empty response is then fallback"
    )
    assert captured["body"]["format"] == "json"
    assert captured["body"]["options"]["num_predict"] >= 1000


# ── JSON serialization for CLI / JSONL logging ──────────────────

def test_judge_result_is_json_serializable():
    r = _fallback_result(SAMPLE_REPORTS, "raw")
    data = asdict(r)
    assert json.loads(json.dumps(data)) == data
