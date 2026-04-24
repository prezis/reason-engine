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
