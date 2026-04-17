"""Runs 20-Q eval: each Q through REASON vs single-shot baseline, blind-judged."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


def load_questions(path: str | Path) -> list[dict]:
    """Load JSONL question set."""
    p = Path(path)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


@dataclass
class EvalResult:
    question_id: str
    reason_answer: str
    baseline_answer: str
    judge_verdict: str  # "reason" | "baseline" | "tie"
    judge_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
