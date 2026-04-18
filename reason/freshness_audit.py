# reason/freshness_audit.py
"""Weekly audit: scan vault, compute staleness + importance, write report."""
from __future__ import annotations
import os
import re
import time
from collections import Counter
from pathlib import Path

from reason.freshness import parse_frontmatter


VAULT = Path(os.path.expanduser("~/ai/global-graph"))
REPORT_DIR = VAULT / "reports"


def score_doc(path: Path, fm: dict, incoming: int) -> tuple[str, dict]:
    now = time.time()
    last_verified_ts = 0.0
    for e in fm.get("last_verified_entries", []) or []:
        try:
            ts_str = e.get("ts", "")
            t = time.strptime(ts_str.rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
            last_verified_ts = max(last_verified_ts, time.mktime(t))
        except Exception:
            continue
    age_days = (now - last_verified_ts) / 86400 if last_verified_ts else 999

    status = fm.get("status", "current")
    if status in ("deprecated", "superseded"):
        return "red", {"status": status, "age_days": age_days}

    stale_votes = sum(
        1 for e in fm.get("session_feedback", []) or []
        if e.get("vote") == "seems-stale"
    )

    if stale_votes >= 3:
        return "red", {"stale_votes": stale_votes, "age_days": age_days}
    if age_days > 90 or stale_votes >= 1:
        return "yellow", {"age_days": age_days, "stale_votes": stale_votes,
                           "incoming": incoming}
    return "green", {"age_days": age_days, "incoming": incoming}


def count_incoming_links(vault: Path) -> Counter:
    wl = re.compile(r"\[\[([^\]|#]+)")
    incoming: Counter = Counter()
    for md in vault.rglob("*.md"):
        try:
            for m in wl.finditer(md.read_text(errors="ignore")):
                target = m.group(1).strip()
                incoming[target] += 1
        except Exception:
            continue
    return incoming


def run_audit(vault: Path = VAULT) -> str:
    incoming = count_incoming_links(vault)
    rows = []
    for md in vault.rglob("*.md"):
        try:
            fm, _ = parse_frontmatter(md.read_text(errors="ignore"))
        except Exception:
            continue
        rel = str(md.relative_to(vault))
        in_count = incoming.get(rel.replace(".md", ""), 0) + incoming.get(rel, 0)
        level, details = score_doc(md, fm, in_count)
        rows.append((level, rel, details))

    order = {"red": 0, "yellow": 1, "green": 2}
    rows.sort(key=lambda r: (order[r[0]], -r[2].get("incoming", 0)))

    ts = time.strftime("%Y-%m-%d", time.gmtime())
    lines = [
        "---",
        "kind: report",
        "mutability: frozen",
        "topics: [_moc-context-engineering]",
        f"name: Freshness audit {ts}",
        "---",
        "",
        f"# Freshness Audit — {ts}",
        "",
        f"Total docs scanned: {len(rows)}",
    ]
    by_level = Counter(r[0] for r in rows)
    lines.append(f"\U0001f7e2 green: {by_level['green']}  \U0001f7e1 yellow: {by_level['yellow']}  \U0001f534 red: {by_level['red']}")
    lines.append("")
    lines.append("| Level | Doc | Incoming | Age (days) | Stale votes |")
    lines.append("|---|---|---:|---:|---:|")
    for level, rel, d in rows:
        icon = {"green": "\U0001f7e2", "yellow": "\U0001f7e1", "red": "\U0001f534"}[level]
        lines.append(
            f"| {icon} | `{rel}` | {d.get('incoming', 0)} | "
            f"{int(d.get('age_days', 0))} | {d.get('stale_votes', 0)} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    report = run_audit()
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"freshness-{time.strftime('%Y-%m-%d')}.md"
    out.write_text(report)
    print(str(out))
