"""Eval runner — loads question set, invokes both pipelines, writes results."""
import json
from pathlib import Path
import pytest
from reason.eval_runner import load_questions, EvalResult


def test_load_questions_from_jsonl(tmp_path):
    f = tmp_path / "qs.jsonl"
    f.write_text('{"id":"q1","category":"code","q":"Use WAL?","expected_strong":["yes for concurrent"]}\n')
    qs = load_questions(f)
    assert len(qs) == 1
    assert qs[0]["id"] == "q1"
    assert qs[0]["category"] == "code"


def test_eval_result_schema():
    r = EvalResult(question_id="q1", reason_answer="...", baseline_answer="...",
                   judge_verdict="reason")
    d = r.to_dict()
    assert d["question_id"] == "q1"
    assert d["judge_verdict"] in ("reason", "baseline", "tie")
