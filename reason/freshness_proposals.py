"""Write freshness proposal files to a queue for human review."""
from __future__ import annotations
import hashlib
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ProposalType(str, Enum):
    DEPRECATE = "deprecate"
    SUPERSEDE = "supersede"
    MERGE = "merge"


@dataclass
class ProposalWriter:
    proposals_dir: Path | str = "~/ai/global-graph/proposals"

    def __post_init__(self) -> None:
        self.proposals_dir = Path(os.path.expanduser(str(self.proposals_dir)))
        self.proposals_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        target: str,
        proposed_by: str,
        proposal_type: ProposalType,
        rationale: str,
        evidence: list[str],
        suggested_replacement: str | None = None,
    ) -> Path:
        if proposal_type == ProposalType.SUPERSEDE and not suggested_replacement:
            raise ValueError("SUPERSEDE requires suggested_replacement")

        ts = time.strftime("%Y-%m-%d", time.gmtime())
        sanitized_target = target.replace("/", "-").replace(".md", "")
        short = hashlib.sha256(
            f"{target}{proposed_by}{time.time_ns()}".encode()
        ).hexdigest()[:6]
        filename = f"pending-{ts}-{sanitized_target}-{proposal_type.value}-{short}.md"
        path = self.proposals_dir / filename

        iso_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lines = [
            "---",
            f"target: {target}",
            f"proposed_by: {proposed_by}",
            f"proposed_ts: {iso_ts}",
            f"type: {proposal_type.value}",
            f"rationale: {rationale!r}",
            "evidence:",
            *[f"  - {e!r}" for e in evidence],
        ]
        if suggested_replacement:
            lines.append(f"suggested_replacement: {suggested_replacement}")
        lines.append("status: pending-human-review")
        lines.append(f"auto-expires-at: {time.strftime('%Y-%m-%d', time.gmtime(time.time() + 30*86400))}")
        lines.append("---")
        lines.append("")
        lines.append(f"# Proposal: {proposal_type.value} {target}")
        lines.append("")
        lines.append(f"**Rationale:** {rationale}")
        lines.append("")
        lines.append("**Evidence:**")
        for e in evidence:
            lines.append(f"- {e}")
        if suggested_replacement:
            lines.append("")
            lines.append(f"**Suggested replacement:** [[{suggested_replacement}]]")
        lines.append("")
        lines.append(f"To approve: `/approve {path.name[:-3]}`")
        lines.append(f"To reject: `/reject {path.name[:-3]}`")

        path.write_text("\n".join(lines))
        return path
