"""Built-in rubric judge — scores REASON worker reports via qwen3.5:27b on local Ollama.

Self-contained reference judge for REASON Stage 3. Use this when you don't
have a dedicated MCP server exposing a judge tool — the slash command
falls back to the CLI here (`python -m reason.judge`) if the MCP tool
isn't registered.

Depends on: `httpx`, a running Ollama on localhost:11434, and a judging
model (default `qwen3.5:27b`, override via env or CLI).

Usage (CLI):
    echo '{"question": "...", "abstract_q": "...", "worker_reports": [...]}' \\
        | python -m reason.judge

Emits JSON to stdout:
    {"scores": {"<role>": {"<criterion>": N, ...}}, "ranking": [...],
     "degraded": false, "raw": null}

Usage (Python):
    from reason.judge import rubric_judge_sync
    result = rubric_judge_sync(question, abstract_q, worker_reports)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("REASON_OLLAMA_URL", "http://localhost:11434/api/generate")
DEFAULT_MODEL = os.environ.get("REASON_JUDGE_MODEL", "qwen3.5:27b")
# Keep-alive extension for the rubric judge. "30m" keeps the model warm across
# back-to-back /reason invocations without blocking other callers — set per
# request (not globally) for multi-session safety.
DEFAULT_KEEP_ALIVE = os.environ.get("REASON_OLLAMA_KEEP_ALIVE", "5m")
CRITERIA = (
    "correctness",
    "evidence_quality",
    "logical_soundness",
    "completeness",
    "cites_or_synthesizes",
)


@dataclass
class JudgeResult:
    scores: dict[str, dict[str, Any]]
    ranking: list[str]
    degraded: bool = False
    raw: str | None = None


def _build_prompt(question: str, abstract_q: str, worker_reports: list[dict]) -> str:
    header = (
        "You are a strict rubric judge. Score each worker's report on 5 criteria "
        "(each 1-5, integers only). Output ONLY valid JSON matching the schema below.\n\n"
        "Criteria:\n"
        "- correctness:        does the claim hold given the question?\n"
        "- evidence_quality:   is evidence cited and relevant?\n"
        "- logical_soundness:  no non-sequiturs, no contradictions?\n"
        "- completeness:       covers key angles or acknowledges gaps?\n"
        "- cites_or_synthesizes: names sources OR clearly labels synthesis.\n\n"
        f"Question: {question}\n"
        f"Step-back abstraction: {abstract_q}\n\n"
        "Worker reports:\n"
    )
    body = "\n\n".join(
        f"### {w['role']}\n{w['report']}" for w in worker_reports
    )
    roles = [w["role"] for w in worker_reports]
    footer = (
        "\n\nOutput JSON schema:\n"
        "{\n"
        '  "scores": {\n'
        + "\n".join(
            f'    "{r}": {{"correctness":N, "evidence_quality":N, '
            f'"logical_soundness":N, "completeness":N, '
            f'"cites_or_synthesizes":N, "rationale":"..."}},'
            for r in roles
        )
        + "\n  },\n"
        '  "ranking": [...]\n'
        "}\n"
    )
    return header + body + footer


def _extract_json_text(resp: dict) -> str:
    """Return JSON-bearing text from an Ollama response.

    qwen3.x thinking variants emit structured output into `thinking` rather
    than `response` when `think: False` isn't honored. Accept either; prefer
    `response`. See docs/qwen-thinking-mode.md in prezis/local-ai-mcp.
    """
    r = (resp.get("response", "") or "").strip()
    if r:
        return r
    return (resp.get("thinking", "") or "").strip()


def _fallback_result(worker_reports: list[dict], raw: str | None) -> JudgeResult:
    default_scores = {
        w["role"]: {**{c: 3 for c in CRITERIA}, "rationale": "judge output unparseable"}
        for w in worker_reports
    }
    return JudgeResult(
        scores=default_scores,
        ranking=[w["role"] for w in worker_reports],
        degraded=True,
        raw=(raw[:500] if raw else None),
    )


def rubric_judge_sync(
    question: str,
    abstract_q: str,
    worker_reports: list[dict],
    model: str = DEFAULT_MODEL,
    timeout: float = 60.0,
) -> JudgeResult:
    """Synchronous rubric judge call. Use this from the CLI / hook / Bash."""
    import httpx  # local import so tests can stub

    prompt = _build_prompt(question, abstract_q, worker_reports)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": DEFAULT_KEEP_ALIVE,
        "options": {"temperature": 0.1, "num_predict": 2000, "num_ctx": 8192},
    }
    try:
        resp = httpx.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("ollama call failed: %s", e)
        return _fallback_result(worker_reports, str(e))

    raw = _extract_json_text(data)
    try:
        parsed = json.loads(raw)
        scores = parsed["scores"]
        ranking = parsed["ranking"]
        for s in scores.values():
            for c in CRITERIA:
                v = s.get(c, 3)
                try:
                    s[c] = max(1, min(5, int(v)))
                except (TypeError, ValueError):
                    s[c] = 3
        return JudgeResult(scores=scores, ranking=ranking)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.warning("judge output parse failed: %s; raw=%r", e, raw[:200])
        return _fallback_result(worker_reports, raw)


# ── CLI ──────────────────────────────────────────────────────────

def _cli(argv: list[str]) -> int:
    """Usage: echo '<json>' | python -m reason.judge [--model qwen3.5:27b]

    Input JSON (stdin):
        {"question": "...", "abstract_q": "...",
         "worker_reports": [{"role": "...", "report": "..."}, ...]}

    Output JSON (stdout):
        {"scores": {...}, "ranking": [...], "degraded": false, "raw": null}

    Exit 0 always (degraded flag in output); exit 2 on malformed stdin.
    """
    model = DEFAULT_MODEL
    if "--model" in argv:
        i = argv.index("--model")
        if i + 1 < len(argv):
            model = argv[i + 1]

    try:
        payload = json.loads(sys.stdin.read())
        question = str(payload["question"])
        abstract_q = str(payload["abstract_q"])
        worker_reports = payload["worker_reports"]
        assert isinstance(worker_reports, list) and len(worker_reports) >= 1
    except (json.JSONDecodeError, KeyError, AssertionError, ValueError) as e:
        print(
            json.dumps({"error": f"bad stdin: {e}", "expected": {
                "question": "str", "abstract_q": "str",
                "worker_reports": [{"role": "str", "report": "str"}],
            }}),
            file=sys.stderr,
        )
        return 2

    result = rubric_judge_sync(question, abstract_q, worker_reports, model=model)
    print(json.dumps(asdict(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
