"""Append-only JSONL audit log for REASON invocations."""
from __future__ import annotations
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any


@dataclass
class AuditRecord:
    stage: str
    payload: dict[str, Any]
    ts: float = field(default_factory=time.time)


class AuditLog:
    """Append-only JSONL audit log.

    Supports context-manager protocol for guaranteed fd cleanup:
        with AuditLog() as log:
            inv = log.start_invocation(...)
            log.write(inv, ...)
            log.close(inv)
        # all still-open handles auto-closed at __exit__

    Also implements __del__ as last-resort cleanup if neither close() nor
    the context-manager path is taken (e.g., orchestrator crash between
    start_invocation and explicit close).
    """

    def __init__(self, base_dir: Path | str = "~/.reason-logs"):
        self.base_dir = Path(os.path.expanduser(str(base_dir)))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, int] = {}

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close_all()

    def __del__(self):
        # Defensive: the GC may run this long after useful context. Best
        # effort — swallow errors, we're on the cleanup path.
        try:
            self.close_all()
        except Exception:
            pass

    def start_invocation(self, question: str, mode: str) -> str:
        ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        ns = time.monotonic_ns() % 1_000_000
        qhash = hashlib.sha256(question.encode("utf-8")).hexdigest()[:8]
        invocation_id = f"{ts}-{ns:06d}-{qhash}"
        path = self.base_dir / f"{invocation_id}.jsonl"
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self._handles[invocation_id] = fd
        start_rec = {"stage": "start", "question": question, "mode": mode,
                     "ts": time.time(), "invocation_id": invocation_id}
        os.write(fd, (json.dumps(start_rec, ensure_ascii=False) + "\n").encode("utf-8"))
        return invocation_id

    def write(self, invocation_id: str, record: AuditRecord) -> None:
        fd = self._handles.get(invocation_id)
        if fd is None:
            raise RuntimeError(f"unknown invocation_id: {invocation_id}")
        line = json.dumps(asdict(record), ensure_ascii=False) + "\n"
        os.write(fd, line.encode("utf-8"))

    def close(self, invocation_id: str) -> None:
        fd = self._handles.pop(invocation_id, None)
        if fd is not None:
            os.close(fd)

    def close_all(self) -> None:
        """Close every open invocation handle. Idempotent."""
        for inv_id in list(self._handles.keys()):
            self.close(inv_id)
