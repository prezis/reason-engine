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

## Install — one command

This repo is the canonical source for the whole skill. Clone it, run the
install script, done:

```bash
git clone https://github.com/prezis/reason-engine.git ~/ai/reason-engine
cd ~/ai/reason-engine
python -m venv .venv && source .venv/bin/activate
./scripts/install-skill.sh
```

What the script does (idempotent, safe to re-run):

1. Copies `claude/commands/reason.md` + `claude/commands/reason/workers/*.md`
   to `~/.claude/commands/` so the `/reason` slash command resolves.
2. Copies `claude/enforcements/reason-validator.py` +
   `claude/enforcements/reason-trigger.py` to `~/.claude/enforcements/`.
3. Registers a `PostToolUse(Agent)` hook in `~/.claude/settings.json`
   (creates a minimal `settings.json` if none exists).
4. Runs `pip install -e .` so `python -m reason.validator` is on PATH.
5. Runs `pytest -q` to confirm the install.

Knobs: `CLAUDE_DIR=/custom/path`, `SKIP_PIP=1`, `SKIP_TESTS=1`.

### Optional Layer-5 — rubric judge MCP tool

The Stage-3 rubric judge runs on [prezis/local-ai-mcp](https://github.com/prezis/local-ai-mcp).
That dependency is optional — the slash command's Stage 4 degrades gracefully
to majority-vote + confidence labels if the MCP tool is missing. Install
`local-ai-mcp` separately per its README if you want cross-model judging
via local qwen3.5:27b.

## Repo layout

```
reason-engine/
├── reason/                     # Python package (parser, validator,
│   │                             semantic_sampler, audit, trigger)
│   └── ...
├── claude/                     # Claude Code skill artifacts (canonical)
│   ├── commands/
│   │   ├── reason.md           # /reason slash command orchestrator
│   │   └── reason/workers/     # 5 role prompts (adversarial, skeptic,
│   │                             synthesist, domain-expert, baseline)
│   └── enforcements/
│       ├── reason-validator.py # PostToolUse(Agent) hook — Layer-1 gate
│       └── reason-trigger.py   # UserPromptSubmit hook — auto-invoke
├── tests/                      # 140+ tests covering all of the above
├── scripts/
│   └── install-skill.sh        # one-command install + settings wiring
├── pyproject.toml
├── README.md
└── LICENSE                     # MIT
```

## Development workflow

If you're editing the skill (as opposed to using it):

- Edit files under `claude/` in this repo first, not under `~/.claude/`
  directly. This repo is the source of truth.
- After editing, re-run `./scripts/install-skill.sh` to redeploy into
  `~/.claude/`. The script is idempotent; it won't re-register the hook.
- Tests live under `tests/` and cover prompts, validator, semantic sampler,
  parser, slash command, and hook behavior (via subprocess).

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
