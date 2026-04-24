# REASON Engine

Step-back + role-diverse workers + rubric-judge reasoning pipeline for Claude Code.

## What it does

Turns a `/reason <question>` slash command into a 4-stage pipeline:

1. **Step-back** — rephrase the question at a higher level of abstraction
   ([Zheng et al. 2024](https://arxiv.org/abs/2310.06117)).
2. **5 parallel workers** — adversarial, skeptic, synthesist, domain-expert,
   baseline. Each gets the original question + the step-back abstract + its
   role prompt. Dispatched in a single Claude Code message (true parallel).
3. **Rubric judge** — `qwen3.5:27b` scores each worker across 5 criteria on a
   local GPU. Zero Claude tokens for the judging step.
4. **Synthesis** — confidence-calibrated final answer: Strong (>=3/5 workers +
   judge >=4.0) / Weaker (1-2 workers + judge >=3.5) / Rejected (judge <=2).

Optional `--mode=debate` replaces Stage 2 with a 2-worker pro/anti debate +
refutation round (opt-in for asymmetric-info regimes with verifiable evidence).

## What's in this repo

Pure Python library — the stateful pieces the live pipeline imports:

- `reason/trigger.py` — detects whether a user prompt warrants `/reason` (used
  by the optional UserPromptSubmit hook).
- `reason/audit.py` — atomic append-only JSONL logger for each stage.
- `reason/eval_runner.py` — eval harness for worker/judge regression tests.
- `reason/freshness*.py` — vault-freshness audit/proposal utilities that grew
  alongside the engine.

No LLM keys, no network calls baked in. The workers run inside Claude Code as
subagents; the judge runs locally via
[prezis/local-ai-mcp](https://github.com/prezis/local-ai-mcp).

## Install — full pipeline

You need four pieces. Three are public repos; this one is the fourth.

### 1. This engine

```bash
git clone https://github.com/prezis/reason-engine.git ~/ai/reason-engine
cd ~/ai/reason-engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q   # should be all green
```

### 2. Slash command + 5 worker prompts

Lives in [prezis/dotfiles](https://github.com/prezis/dotfiles):

```bash
# from the dotfiles repo
cp .claude/commands/reason.md                  ~/.claude/commands/
cp -r .claude/commands/reason/                 ~/.claude/commands/
```

- `reason.md` — the `/reason` slash command (orchestrator).
- `reason/workers/{adversarial,skeptic,synthesist,domain-expert,baseline}.md`
  — the 5 role prompts.

### 3. (Optional) Auto-trigger hook

Also in [prezis/dotfiles](https://github.com/prezis/dotfiles):

```bash
cp .claude/enforcements/reason-trigger.py  ~/.claude/enforcements/
```

Wire it into `settings.json` as a `UserPromptSubmit` hook. It uses
`reason.trigger.detect_trigger` from this repo to flag prompts that would
benefit from `/reason` (non-trivial, multi-domain, high-stakes).

### 4. Rubric judge MCP tool

Lives in [prezis/local-ai-mcp](https://github.com/prezis/local-ai-mcp). The
slash command calls `mcp__local-ai__local_rubric_judge` in Stage 3. Requires
a local Ollama with `qwen3.5:27b` (or any model you wire in). Install the
MCP server per its README and the judge tool is available.

## Grounding contract — why the workers actually invoke tools

The `/reason` pipeline is only useful if workers check real sources instead of
generating plausible-sounding prose from training data. The failure mode we
observed (and then fixed) was: every worker finishing with `0 tool uses`,
producing role-differentiated-but-unverified opinions, which the orchestrator
then synthesized into a plan that looked grounded but wasn't.

The fix lives in two layers:

1. **Imperative worker prompts.** Each empirical role (adversarial, skeptic,
   synthesist, domain-expert) opens with a `## MANDATORY PRE-WORK` block that
   names concrete tools to call (`Grep`, `Read`, `Glob`, `mcp__qmd__search`,
   `mcp__qmd__vector_search`, `mcp__local-ai__local_web_search`) and the
   minimum number of files to actually `Read`. Declarative "you have access
   to the vault" is replaced with imperative "run `Grep` on these keywords".

2. **Verifiable citation format.** Citations must take the form
   `path/file.md:L23-L45 > "exact quoted snippet"` — invented `[[wikilinks]]`
   are explicitly flagged as red-flag behavior. Line-range-plus-quote forces
   a real `Read` call to produce.

The `baseline` worker is **tool-less by design** — its distinctive YAGNI voice
comes from first-reaction intuition, not vault lookup. It explicitly declares
itself as such so `0 tool uses` there isn't mistaken for a grounding failure.

Every empirical worker's output format requires a `Tool-use summary` field so
the rubric judge (Stage 3) can detect and downweight low-grounding reports.

Regression guarded by `tests/test_worker_prompts.py` — the contract tests will
fail if a future edit strips the `MANDATORY PRE-WORK` block, removes tool
names, drops the line-range citation format, or accidentally adds tool
mandates to baseline.

## Runtime enforcement (Layer-1 + Layer-5 per defeating-lussers-law.md)

Prompt-level mandates are requests to the LLM, not guarantees. The engine
ships two deterministic enforcement layers that run outside the worker's
control loop — the agent cannot skip them:

**Layer 1 — Structural validator (`reason/validator.py`)**
- Triggered by a `PostToolUse(Agent)` hook whenever a REASON worker
  subagent completes (`~/.claude/enforcements/reason-validator.py`).
- Parses the worker's final message via `reason.parser.parse_worker_report`.
- Applies role-aware thresholds (see `ROLE_THRESHOLDS` in validator.py):
  empirical workers need ≥1–3 tool uses and ≥2–3 citations; baseline is
  exempt (tool-less by design).
- For every `path:Lstart-Lend > "quote"` citation: resolves the path
  against search roots, checks the line range is within the file, checks
  the quote is a substring of the file text at that range.
- Writes a validation record to `~/.reason-logs/<session_id>/validation.jsonl`.
- WARN mode by default — logs violations to stderr but never blocks the
  tool chain. Promotion to BLOCK happens after ~20 live calibration runs,
  matching the kopanie `post-change-validate.json` WARN→BLOCK precedent.

**Layer 5 — Semantic sampler (`reason/semantic_sampler.py`)**
- Catches the failure mode the structural validator cannot: a quote that
  exists at the cited range but doesn't actually support the claim.
- Samples 20% of validated citations (deterministic, seed-based) and
  routes each through `qwen3.5:27b` on local Ollama with a minimal prompt
  containing only `(file_text_at_range, claim_context, quote)` — no
  reasoning trace, so the judge can't be cued.
- Returns per-citation verdicts: `supports | partial | unrelated | unknown
  | file_missing`. Any `unrelated` verdict fails the semantic gate.
- Cross-model by design: workers run on Claude; the judge runs on a
  different model family entirely.

The validator + hook are regression-guarded by:
- `tests/test_parser.py` (10 tests) — parser correctness
- `tests/test_validator.py` (15 tests) — role thresholds + filesystem checks
- `tests/test_semantic_sampler.py` (10 tests) — sampling + verdict parsing
- `tests/test_hook_integration.py` (6 tests) — end-to-end subprocess call

The hook is wired via `PostToolUse` matcher `"Agent"` in
`~/.claude/settings.json`. The CLI entry point `python -m reason.validator`
is also available for manual or CI invocation.

## Usage

In any Claude Code session:

```
/reason should I use Polars or DuckDB for a 50GB parquet analytics workload?
```

or with debate mode:

```
/reason --mode=debate is microservice X the right seam to split the monolith?
```

Logs land in `~/.reason-logs/<ts>-<hash>.jsonl` (one record per stage, atomic
append).

## Design origin

Built via TDD (19 commits, `test_smoke` -> `test_trigger` -> `test_audit_log`
-> `test_freshness_*` -> `test_e2e_smoke`). All tests green.

The design itself was pressure-tested with REASON (yes, meta): step-back ->
5 workers -> `qwen3.5:27b` rubric -> confidence-calibrated synthesis.

## License

MIT — see [LICENSE](LICENSE).
