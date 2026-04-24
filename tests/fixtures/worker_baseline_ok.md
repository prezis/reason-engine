# SIMPLE-BASELINE: The Dumb Direct Answer

**Simplest possible answer:** (A) — PostToolUse hook + deterministic Python validator. Not (C), because (C) is just (A) with homework attached.

**What makes it sufficient:** The actual failure mode is "agent skips a mandatory step." That's a 5-line check: did file X get written? did tool Y appear in the transcript? A regex + filesystem stat, exit 0 or 1.

**What additional complexity would add:** LangGraph gives you typed state, retry edges, checkpoint-resume. Costs: new dependency, second mental model, SQLite schema, Pydantic drift.

**Failure modes of simple answer:**
- Regex validator rots when output format changes
- No automatic retry on partial failure
- Can't inspect intermediate state post-hoc

**Tool-use summary:** 0 — tool-less by design.

**Confidence: 4/5**
