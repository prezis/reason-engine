"""Audit log writer — atomic append of JSONL records."""
import json
from pathlib import Path
import pytest
from reason.audit import AuditLog, AuditRecord


def test_audit_creates_file_and_writes_record(tmp_path):
    log = AuditLog(base_dir=tmp_path)
    invocation_id = log.start_invocation(question="test question", mode="default")
    log.write(invocation_id, AuditRecord(stage="step_back",
                                          payload={"abstract": "abstract version"}))
    log.close(invocation_id)

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 2  # start + step_back
    start = json.loads(lines[0])
    assert start["stage"] == "start"
    assert start["question"] == "test question"
    sb = json.loads(lines[1])
    assert sb["stage"] == "step_back"
    assert sb["payload"]["abstract"] == "abstract version"


def test_audit_handles_large_payloads(tmp_path):
    """Worker reports may exceed PIPE_BUF (4096) — must still write cleanly."""
    log = AuditLog(base_dir=tmp_path)
    big_payload = {"report": "x" * 10_000}
    inv = log.start_invocation(question="q", mode="default")
    log.write(inv, AuditRecord(stage="worker", payload=big_payload))
    log.close(inv)

    files = list(tmp_path.glob("*.jsonl"))
    lines = files[0].read_text().strip().split("\n")
    worker_line = [l for l in lines if "worker" in l][0]
    rec = json.loads(worker_line)
    assert len(rec["payload"]["report"]) == 10_000


def test_audit_filename_is_deterministic_per_invocation(tmp_path):
    log = AuditLog(base_dir=tmp_path)
    inv1 = log.start_invocation(question="a question", mode="default")
    inv2 = log.start_invocation(question="a question", mode="default")
    assert inv1 != inv2


def test_audit_context_manager_closes_handles(tmp_path):
    """Context manager must release fds at __exit__ even if caller forgets close()."""
    with AuditLog(base_dir=tmp_path) as log:
        inv = log.start_invocation(question="q", mode="default")
        log.write(inv, AuditRecord(stage="mid", payload={"x": 1}))
        # intentionally do NOT call log.close(inv)
        assert inv in log._handles
    assert log._handles == {}


def test_audit_close_all_is_idempotent(tmp_path):
    log = AuditLog(base_dir=tmp_path)
    log.start_invocation(question="q1", mode="default")
    log.start_invocation(question="q2", mode="default")
    log.close_all()
    log.close_all()  # second call must not raise
    assert log._handles == {}
