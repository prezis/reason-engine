import pytest
from pathlib import Path
from reason.freshness_proposals import ProposalWriter, ProposalType


def test_writer_creates_file_in_proposals_dir(tmp_path):
    w = ProposalWriter(proposals_dir=tmp_path)
    path = w.write(
        target="patterns/foo.md",
        proposed_by="session-abc",
        proposal_type=ProposalType.DEPRECATE,
        rationale="model no longer pinned",
        evidence=["pins.json missing qwen2.5:3b"],
    )
    assert path.exists()
    assert "pending-" in path.name
    assert path.name.endswith(".md")
    content = path.read_text()
    assert "target: patterns/foo.md" in content
    assert "proposed_by: session-abc" in content
    assert "type: deprecate" in content


def test_writer_includes_suggested_replacement_for_supersede(tmp_path):
    w = ProposalWriter(proposals_dir=tmp_path)
    path = w.write(
        target="patterns/old.md",
        proposed_by="session-abc",
        proposal_type=ProposalType.SUPERSEDE,
        rationale="replaced by v2",
        evidence=["diff of responsibilities in v2"],
        suggested_replacement="patterns/new.md",
    )
    assert "suggested_replacement: patterns/new.md" in path.read_text()


def test_writer_rejects_supersede_without_replacement(tmp_path):
    w = ProposalWriter(proposals_dir=tmp_path)
    with pytest.raises(ValueError, match="suggested_replacement"):
        w.write(
            target="x.md",
            proposed_by="s",
            proposal_type=ProposalType.SUPERSEDE,
            rationale="r",
            evidence=["e"],
        )
