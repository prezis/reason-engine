---
description: "REASON engine — step-back + 5-worker + rubric-judge reasoning pipeline. Use for non-trivial questions. Supports --mode=debate for asymmetric-info regimes."
argument-hint: [--mode=debate] <question>
allowed-tools: Read,Write,Edit,Bash,Grep,Glob,Agent
---

# REASON orchestrator

User question: $ARGUMENTS

Parse `--mode=debate` from arguments if present; otherwise default mode.

## Stage 1 — Step-back reformulation

Rephrase the question at a higher level of abstraction (the general principle or
class of problem). Output as `abstract_q`. Reference:
[Zheng et al. 2024, "Take a Step Back", arxiv:2310.06117].

## Stage 2 — Dispatch 5 parallel workers (default mode) OR 2 workers (debate mode)

**Default mode:** dispatch 5 subagents in ONE assistant message (true parallel). Each
receives the ORIGINAL question, the step-back abstract, and its role prompt from
`~/.claude/commands/reason/workers/<role>.md`.

Roles: adversarial, skeptic, synthesist, domain-expert, baseline.

**Debate mode:** 2 workers with opposing stances — pro_X and anti_X. See debate-preset
section below.

## Stage 3 — Rubric judge

**Judge source (try in order):**

1. **MCP tool (preferred when registered).** Call `mcp__local-ai__local_rubric_judge`
   with: question, abstract_q, worker_reports. Model: qwen3.5:27b. Zero
   Claude tokens. Returns per-worker scores 1-5 across 5 criteria + ranking.

2. **Built-in CLI (fallback when the MCP tool is not registered).** Invoke
   via Bash:
   ```
   echo '<json>' | python -m reason.judge
   ```
   where `<json>` is `{"question": "...", "abstract_q": "...", "worker_reports": [{"role": "...", "report": "..."}, ...]}`.
   Same qwen3.5:27b, same rubric schema, same output. Requires Ollama
   running on localhost:11434 with `qwen3.5:27b` pulled.

3. **Claude-internal fallback (last resort).** If neither the MCP tool nor
   Ollama is available, score the workers yourself against the same 5
   criteria and explicitly flag `degraded: true` + `judge_source: "claude-inline"`
   in the Stage-4 Grounding-audit footer. This is the same-family
   self-grading anti-pattern — acknowledge it so the user knows quality
   is reduced.

**Grounding check (before judge scoring):**

1. **Authoritative source — runtime validator.** Read
   `~/.reason-logs/<session_id>/validation.jsonl` (one JSONL record per
   dispatched worker, written by the `reason-validator.py` PostToolUse
   hook). Each record contains `role`, `ok`, `tool_uses_count`,
   `citations_valid / citations_checked`, `grounding_score`, and
   `violations[]`. If the record shows `ok: false`, tag that worker as
   `low-grounding` with the specific violation kinds as the reason.
2. **Fallback — prompt-level audit.** If (and only if) the validation.jsonl
   is missing for a worker (e.g. hook disabled, log dir override), inspect
   the worker's `Tool-use summary` field directly: empty, "0 tool uses",
   or no real `path:Lstart-Lend > "quote"` citations → tag low-grounding.

The runtime validator is authoritative because it's written by
deterministic Python outside the worker's control loop; the prompt-level
check is the worker's self-report and can be gamed. Baseline is exempt
from both paths (tool-less by design).

## Stage 4 — Synthesis

Produce final answer with CONFIDENCE CALIBRATION. Structure:
- **Strong (≥3/5 workers + avg judge score ≥4.0 + at least 2 of those workers NOT tagged low-grounding):** claims listed here
- **Weaker (novel; 1-2 workers + judge ≥3.5):** claims here
- **Rejected (judge ≤2 OR baseline worker refuted OR all supporting workers low-grounding):** claims here

A claim supported only by low-grounding workers drops one confidence tier
(Strong → Weaker, Weaker → Rejected) regardless of judge score. Baseline
refutation still moves a claim to Rejected — the YAGNI voice is authoritative
on over-engineering even without tools.

Do NOT output a single verdict — output the confidence-labeled claim list.
Include a short "Grounding audit" footer listing which workers were tagged
low-grounding and how that affected the synthesis.

## Audit

Use `reason.audit.AuditLog` from `~/ai/reason-engine/reason/audit.py` to log each
stage to `~/.reason-logs/<ts>-<hash>.jsonl`.

## Debate-preset section (if --mode=debate)

Replace Stage 2 with:
1. 2 workers get opposing stances (pro, anti). Each writes opening argument (400-800w).
2. Each worker receives opponent's argument → writes refutation (200-400w).
3. Judge scores ONLY the refutation round.

Only use debate mode when explicitly requested. Research (Du 2023, Khan 2024, Wang
2025) shows default debate hurts — it lives here as an opt-in for asymmetric-info
regimes with verifiable evidence.
