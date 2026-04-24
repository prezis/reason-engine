"""Layer-5 semantic grounding gate (per `patterns/defeating-lussers-law.md`).

Structural validation (reason.validator) catches fabricated paths and quotes
that don't exist at cited line ranges. It does NOT catch the harder failure
mode: a quote that exists at the cited range but doesn't actually SUPPORT
the claim it's attached to. That bypass requires an independent judge that
re-reads the source and compares to the worker's claim.

This module implements that judge:

  1. Sample a subset of citations (default 20%, deterministic via seed).
  2. For each sampled citation, build a minimal prompt containing only
     (file_text_at_range, claim_context, quote) — NOT the worker's reasoning
     trace, so the judge can't be cued.
  3. Route through a pluggable `backend(prompt: str) -> str`. The default
     backend calls qwen3.5:27b on local Ollama (cross-model — different
     family from any Claude worker).
  4. Parse the verdict JSON and return a `SemanticVerdict` per citation.

The backend abstraction lets us test the sampling + prompt-shape logic
without network I/O.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Iterable

from reason.parser import Citation, WorkerReport


# ── public types ─────────────────────────────────────────────────

Backend = Callable[[str], str]
FileReader = Callable[[str], str]


@dataclass(frozen=True)
class SamplerConfig:
    sample_rate: float = 0.2
    max_sample: int = 10
    seed: int = 0


@dataclass
class SemanticVerdict:
    citation: Citation
    verdict: str  # "supports" | "partial" | "unrelated" | "unknown" | "file_missing"
    confidence: float
    rationale: str = ""


# ── sampling ─────────────────────────────────────────────────────

def sample_citations(
    citations: list[Citation], config: SamplerConfig
) -> list[Citation]:
    """Deterministic sample. With a non-zero sample_rate AND at least one
    citation, we always sample at least one — the rate should never silently
    drop grounding to zero for small N."""
    if not citations or config.sample_rate <= 0.0:
        return []
    rng = random.Random(config.seed)
    n = len(citations)
    target = math.ceil(n * config.sample_rate)
    target = max(1, min(target, config.max_sample, n))
    indices = list(range(n))
    rng.shuffle(indices)
    chosen = sorted(indices[:target])
    return [citations[i] for i in chosen]


# ── prompt construction ─────────────────────────────────────────

_PROMPT_TEMPLATE = """You are a verification judge checking whether a quoted passage actually supports a claim.

You will see:
  CLAIM     — a short statement the author is making
  QUOTE     — the author's extracted quote
  SOURCE    — the actual text of the file at the cited line range
  CITATION  — the path and line range

You do NOT have access to the author's reasoning or other evidence. Judge ONLY based on whether the SOURCE contains text that supports the CLAIM by way of the QUOTE.

Respond with exactly one JSON object (no prose before or after) of the form:
{{"verdict": "supports" | "partial" | "unrelated", "confidence": <float 0..1>, "rationale": "<<=25 words>"}}

Decision rules:
  - "supports"  — the SOURCE plainly backs the CLAIM via the QUOTE
  - "partial"   — the QUOTE is in SOURCE but the connection to CLAIM is weak or needs inference
  - "unrelated" — the QUOTE is absent from SOURCE, OR present but clearly does not bear on CLAIM

---
CLAIM: {claim}
QUOTE: {quote}
CITATION: {path}:L{start}-L{end}

SOURCE (the file text at the cited range, verbatim):
{source}
---

Respond with the JSON object now.
"""


def _build_prompt(
    citation: Citation, file_text: str, claim_context: str
) -> str:
    # Extract just the cited line range from the full file text.
    lines = file_text.splitlines()
    n = len(lines)
    start = max(1, citation.line_start)
    end = min(n, citation.line_end)
    if start > end or start > n:
        source = "(cited range is out of bounds)"
    else:
        source = "\n".join(lines[start - 1 : end])

    return _PROMPT_TEMPLATE.format(
        claim=claim_context.strip()[:800],
        quote=citation.quote,
        path=citation.path,
        start=citation.line_start,
        end=citation.line_end,
        source=source[:4000],  # guardrail against giant ranges
    )


# ── semantic check ───────────────────────────────────────────────

_ALLOWED_VERDICTS = {"supports", "partial", "unrelated"}


def _parse_backend_response(raw: str) -> tuple[str, float, str]:
    """Best-effort parse of the backend's JSON response.

    Returns (verdict, confidence, rationale). Returns ('unknown', 0.0, '')
    if the response is malformed.
    """
    # qwen sometimes wraps in ```json … ``` — strip fences.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    # Take only the first JSON object if extra prose leaked.
    brace_start = cleaned.find("{")
    brace_end = cleaned.rfind("}")
    if brace_start < 0 or brace_end <= brace_start:
        return ("unknown", 0.0, "")
    try:
        data = json.loads(cleaned[brace_start : brace_end + 1])
    except json.JSONDecodeError:
        return ("unknown", 0.0, "")

    verdict = str(data.get("verdict", "")).lower()
    if verdict not in _ALLOWED_VERDICTS:
        return ("unknown", 0.0, str(data.get("rationale", "")))
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    rationale = str(data.get("rationale", ""))[:400]
    return (verdict, confidence, rationale)


def semantic_check_citation(
    citation: Citation,
    file_text: str,
    claim_context: str,
    backend: Backend,
) -> SemanticVerdict:
    """Route a single citation through the backend judge."""
    prompt = _build_prompt(citation, file_text, claim_context)
    raw = backend(prompt)
    verdict, confidence, rationale = _parse_backend_response(raw)
    return SemanticVerdict(
        citation=citation,
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
    )


# ── full-report orchestration ───────────────────────────────────

def check_report(
    report: WorkerReport,
    claim_context: str,
    file_reader: FileReader,
    config: SamplerConfig | None = None,
    backend: Backend | None = None,
) -> list[SemanticVerdict]:
    """Sample `report.citations`, read each file, check each via `backend`.

    If the default Ollama backend is wanted, pass `backend=None` — we try to
    import it lazily. Tests pass a stub.
    """
    cfg = config or SamplerConfig()
    if backend is None:
        backend = _default_ollama_backend

    sample = sample_citations(report.citations, cfg)
    verdicts: list[SemanticVerdict] = []
    for cit in sample:
        try:
            text = file_reader(cit.path)
        except (FileNotFoundError, OSError):
            verdicts.append(
                SemanticVerdict(
                    citation=cit,
                    verdict="file_missing",
                    confidence=0.0,
                    rationale="file reader could not load the path",
                )
            )
            continue
        verdicts.append(
            semantic_check_citation(cit, text, claim_context, backend)
        )
    return verdicts


# ── default backend (Ollama qwen3.5:27b via httpx) ──────────────

_OLLAMA_URL = "http://localhost:11434/api/chat"
_OLLAMA_MODEL = "qwen3.5:27b"


def _default_ollama_backend(prompt: str) -> str:
    """Call qwen3.5:27b on local Ollama. Uses the /api/chat endpoint with
    `think: false` because qwen3.x models otherwise enter a silent-thinking
    mode that emits empty responses inside num_predict-limited budgets.

    Raises if httpx is missing or the request fails — caller should wrap
    or inject a stub backend for tests.
    """
    import httpx  # local import so tests that stub don't need httpx

    resp = httpx.post(
        _OLLAMA_URL,
        json={
            "model": _OLLAMA_MODEL,
            "think": False,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 400},
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", "")


# ── aggregate helper for the hook ───────────────────────────────

@dataclass
class SemanticReport:
    role: str
    sampled: int
    supports: int
    partial: int
    unrelated: int
    unknown: int
    file_missing: int
    verdicts: list[SemanticVerdict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Semantic gate passes if no 'unrelated' verdicts AND < 50% of
        sampled citations are 'file_missing' or 'unknown' combined."""
        if self.unrelated > 0:
            return False
        if self.sampled == 0:
            return True
        bad = self.file_missing + self.unknown
        return bad / self.sampled < 0.5


def summarize(role: str, verdicts: list[SemanticVerdict]) -> SemanticReport:
    counts = {"supports": 0, "partial": 0, "unrelated": 0,
              "unknown": 0, "file_missing": 0}
    for v in verdicts:
        if v.verdict in counts:
            counts[v.verdict] += 1
    return SemanticReport(
        role=role,
        sampled=len(verdicts),
        verdicts=verdicts,
        **counts,
    )
