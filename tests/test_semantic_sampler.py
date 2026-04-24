"""Semantic sampler tests — the Layer-5 gate that catches quotes that exist
at the cited line range but don't actually support the claim.

Tests use a fake backend so they run offline and deterministically.
"""
import pytest

from reason.parser import Citation
from reason.semantic_sampler import (
    SemanticVerdict,
    SamplerConfig,
    sample_citations,
    semantic_check_citation,
    check_report,
)


def _cit(idx: int) -> Citation:
    return Citation(
        path=f"fake{idx}.md", line_start=1, line_end=3, quote=f"quote-{idx}"
    )


# ── sampling (deterministic, pure) ───────────────────────────────

def test_sample_rate_zero_returns_empty():
    cits = [_cit(i) for i in range(10)]
    assert sample_citations(cits, SamplerConfig(sample_rate=0.0)) == []


def test_sample_rate_one_returns_all():
    cits = [_cit(i) for i in range(10)]
    out = sample_citations(cits, SamplerConfig(sample_rate=1.0))
    assert set(out) == set(cits)


def test_sample_respects_max_sample_cap():
    cits = [_cit(i) for i in range(100)]
    out = sample_citations(
        cits, SamplerConfig(sample_rate=1.0, max_sample=5)
    )
    assert len(out) == 5


def test_sample_is_deterministic_for_same_seed():
    cits = [_cit(i) for i in range(20)]
    cfg1 = SamplerConfig(sample_rate=0.3, seed=42)
    cfg2 = SamplerConfig(sample_rate=0.3, seed=42)
    assert sample_citations(cits, cfg1) == sample_citations(cits, cfg2)


def test_sample_respects_minimum_one():
    """With a non-zero sample_rate, at least 1 citation should always be
    sampled if any are present — even if ceil(N*rate) would give 0."""
    cits = [_cit(0), _cit(1)]
    out = sample_citations(cits, SamplerConfig(sample_rate=0.01))
    assert len(out) >= 1


# ── semantic check with injected backend ────────────────────────

def test_semantic_check_supports_verdict():
    def fake_backend(prompt: str) -> str:
        return '{"verdict": "supports", "confidence": 0.9, "rationale": "ok"}'

    v = semantic_check_citation(
        citation=_cit(0),
        file_text="line1\nquote-0 in context\nline3\n",
        claim_context="The pattern exists",
        backend=fake_backend,
    )
    assert isinstance(v, SemanticVerdict)
    assert v.verdict == "supports"
    assert v.confidence == 0.9


def test_semantic_check_unrelated_verdict():
    def fake_backend(prompt: str) -> str:
        return (
            '{"verdict": "unrelated", "confidence": 0.95, '
            '"rationale": "quote exists but does not support the claim"}'
        )

    v = semantic_check_citation(
        citation=_cit(0),
        file_text="line1\nquote-0\nline3\n",
        claim_context="Something entirely different",
        backend=fake_backend,
    )
    assert v.verdict == "unrelated"


def test_semantic_check_malformed_backend_output_is_handled():
    """If qwen returns non-JSON, default to 'unknown' rather than crash."""
    def bad_backend(prompt: str) -> str:
        return "lol not json"

    v = semantic_check_citation(
        citation=_cit(0),
        file_text="x",
        claim_context="y",
        backend=bad_backend,
    )
    assert v.verdict == "unknown"
    assert v.confidence == 0.0


# ── end-to-end check_report ─────────────────────────────────────

def test_check_report_samples_and_calls_backend():
    from reason.parser import WorkerReport

    cits = [_cit(i) for i in range(10)]
    report = WorkerReport(
        role="adversarial",
        raw="",
        tool_uses_count=5,
        citations=cits,
    )

    calls = []

    def tracking_backend(prompt: str) -> str:
        calls.append(prompt)
        return (
            '{"verdict": "supports", "confidence": 0.8, "rationale": "ok"}'
        )

    verdicts = check_report(
        report=report,
        claim_context="the claim",
        file_reader=lambda p: "quote-X\n",  # any non-empty file text
        config=SamplerConfig(sample_rate=0.3, seed=7),
        backend=tracking_backend,
    )

    # 30% of 10 citations = 3 sampled
    assert len(verdicts) == 3
    assert len(calls) == 3
    assert all(v.verdict == "supports" for v in verdicts)


def test_default_backend_uses_chat_endpoint_with_think_false(monkeypatch):
    """Regression guard for the qwen3.x silent-thinking bug — the default
    backend MUST use /api/chat with think=False, otherwise responses come
    back empty inside any reasonable num_predict budget."""
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "ok"}, "done_reason": "stop"}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    from reason.semantic_sampler import _default_ollama_backend
    result = _default_ollama_backend("test prompt")

    assert result == "ok"
    assert captured["url"].endswith("/api/chat"), (
        "default backend must use /api/chat — /api/generate strands qwen3.x "
        "in thinking mode"
    )
    assert captured["body"].get("think") is False, (
        "think:False is required to suppress qwen's silent-thinking output"
    )
    assert "messages" in captured["body"], (
        "chat endpoint requires a messages[] array, not a prompt string"
    )
    assert "keep_alive" in captured["body"], (
        "keep_alive must be present to allow the pipeline to extend the "
        "model's residency without mutating systemd globally"
    )


def test_sampler_model_can_differ_from_judge_via_env(monkeypatch):
    """Layer-5 must allow a cross-family model (e.g. hermes3:8b) without
    changing the Stage-3 rubric judge. Closes the same-family self-grading
    hole flagged by /reason on 2026-04-24."""
    import importlib
    import reason.semantic_sampler as ss

    monkeypatch.setenv("REASON_SEMANTIC_SAMPLER_MODEL", "hermes3:8b")
    # REASON_JUDGE_MODEL intentionally stays at its (legacy) value — the
    # sampler env var must take precedence.
    importlib.reload(ss)

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"message": {"content": "ok"}}

    def fake_post(url, json=None, timeout=None):
        captured["body"] = json
        return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    ss._default_ollama_backend("x")

    assert captured["body"]["model"] == "hermes3:8b"

    # Reload again with env cleared so subsequent tests get the default.
    monkeypatch.delenv("REASON_SEMANTIC_SAMPLER_MODEL", raising=False)
    importlib.reload(ss)


def test_check_report_with_missing_file_marks_unknown():
    from reason.parser import WorkerReport

    cits = [_cit(0)]
    report = WorkerReport(
        role="adversarial", raw="", tool_uses_count=5, citations=cits
    )

    def file_reader(p):
        raise FileNotFoundError(p)

    def backend(prompt):
        raise AssertionError("backend must not be called when file missing")

    verdicts = check_report(
        report=report,
        claim_context="claim",
        file_reader=file_reader,
        config=SamplerConfig(sample_rate=1.0),
        backend=backend,
    )
    assert len(verdicts) == 1
    assert verdicts[0].verdict == "file_missing"
