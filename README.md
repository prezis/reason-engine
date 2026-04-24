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

## Maximum-quality setup (optional but recommended)

The one-command install gets you the core skill — slash command, 5 workers,
structural validator, auto-trigger hook. That works on any Linux/macOS box
with Python.

To unlock the full stack (cross-model rubric judge in Stage 3, Layer-5
semantic citation sampler), you need a local GPU + Ollama + one model:

### 1. Ollama + qwen3.5:27b

```bash
# Linux: curl | sh; macOS: brew install ollama; Windows: .exe installer
curl -fsSL https://ollama.com/install.sh | sh

# Start the service (systemd auto-starts on most Linux distros; macOS uses ollama serve)
systemctl --user start ollama          # Linux
# or:  ollama serve &                  # any OS

# Pull the judge model (~16 GB Q4 quant, ~23 GB VRAM loaded)
ollama pull qwen3.5:27b

# Sanity probe — should return a JSON body with "response"
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3.5:27b","prompt":"2+2=?","stream":false,
       "options":{"num_predict":50},"think":false}' | jq .done_reason
```

**Model sizing by card** (all Q4_K_M quants unless noted):

| GPU | VRAM | Recommended judge model | Loaded size | Notes |
|---|---|---|---|---|
| RTX 5090 / A6000 / H100 | 32+ GB | `qwen3.5:27b` | ~22 GB | Comfortable headroom; default. |
| **RTX 4090 / 3090** | **24 GB** | **`qwen3.5:27b`** | **~22 GB** | **Fits, but tight. If you see OOM during inference, see fallbacks below.** |
| RTX 4080 / 3080 (16 GB) | 16 GB | `qwen3:14b` or `hermes3:8b` | 8-10 GB | Switch via `REASON_JUDGE_MODEL=qwen3:14b`. |
| RTX 4070 / 3070 (12 GB) | 12 GB | `qwen3:8b` | ~5 GB | Quality drop is small for rubric scoring. |
| RTX 4060 / 3060 (8 GB) | 8 GB | `qwen3:4b` | ~3 GB | Minimum viable; expect noisier scores. |
| CPU only | — | `qwen3:4b` on CPU | ~3 GB | Slow (~10-30s per judge call); works. |

**Swapping models — env vars:**

| Env var | Default | Purpose |
|---|---|---|
| `REASON_JUDGE_MODEL` | `qwen3.5:27b` | Stage-3 rubric judge. Called from `python -m reason.judge` and the `local_rubric_judge` MCP tool path. |
| `REASON_SEMANTIC_SAMPLER_MODEL` | falls back to `REASON_JUDGE_MODEL` | **Layer-5 semantic sampler. Set this to a cross-family model to close the same-family self-grading hole** — e.g. `REASON_SEMANTIC_SAMPLER_MODEL=hermes3:8b` while the judge stays on qwen3.5:27b. Validated by the REASON synthesis itself 2026-04-24. |
| `REASON_OLLAMA_KEEP_ALIVE` | `5m` | Per-request keep-alive sent to Ollama. Set to `30m` or `60m` to eliminate cold-swap on back-to-back `/reason` calls without requiring a global systemd change (multi-session safe). |
| `REASON_OLLAMA_URL` | `http://localhost:11434/api/generate` | Judge endpoint override (e.g. remote Ollama). |
| `REASON_OLLAMA_CHAT_URL` | `http://localhost:11434/api/chat` | Sampler endpoint override. |

**Cross-family Layer-5 (recommended if your card has ≥24 GB):** the Stage-3
rubric judge scores whole worker reports (IFEval-heavy task — qwen3.5:27b
wins there). The Layer-5 sampler checks individual quote-supports-claim
decisions (lighter task, benefits from family diversity). Set:

```bash
export REASON_JUDGE_MODEL=qwen3.5:27b           # Stage-3 stays here
export REASON_SEMANTIC_SAMPLER_MODEL=hermes3:8b # Layer-5 gets a different family
export REASON_OLLAMA_KEEP_ALIVE=30m             # keep both warm between calls
```

Requires `ollama pull hermes3:8b` (4.7 GB loaded) and your `OLLAMA_MAX_LOADED_MODELS`
to be ≥ 2 (systemd default is fine).

**4090-specific guidance.** Because qwen3.5:27b loads to ~22 GB on a 24 GB
card, leave the GPU otherwise idle while running /reason (no browser
hardware-acceleration, no other Ollama models resident). If you want a
single model that handles everything comfortably on 24 GB, use
`qwen3:14b` (~8 GB loaded) — it scores well enough on the rubric task
and gives you ~15 GB free for parallel work.

### 2. Stage-3 rubric judge — two paths

**Path A (built-in, no MCP needed) — recommended for external users.**
The slash command's Stage 3 falls back to a built-in CLI automatically:

```bash
echo '{"question":"...","abstract_q":"...","worker_reports":[...]}' \
  | python -m reason.judge
```

Zero extra install — it's already in this repo. Requires only step 1.
The slash command detects the MCP tool is missing and uses this path.

**Path B (MCP tool) — if you want the judge exposed as an MCP tool across
other projects too.** Write a minimal MCP server that wraps
`reason.judge.rubric_judge_sync`. Reference skeleton:

```python
# my-mcp-server/rubric_judge_tool.py
from mcp.server.fastmcp import FastMCP
from reason.judge import rubric_judge_sync
import asyncio

mcp = FastMCP("local-ai")

@mcp.tool()
async def local_rubric_judge(question: str, abstract_q: str,
                              worker_reports: list[dict]) -> dict:
    result = await asyncio.to_thread(
        rubric_judge_sync, question, abstract_q, worker_reports,
    )
    from dataclasses import asdict
    return asdict(result)
```

Register the server in your `~/.claude.json` `mcpServers` section. Details
in the MCP docs at https://modelcontextprotocol.io/.

### 3. Layer-5 semantic citation sampler (automatic)

Once Ollama + qwen3.5:27b are installed (step 1), the semantic sampler
`reason/semantic_sampler.py` works out of the box — it calls Ollama
directly via httpx, no MCP dependency. The `PostToolUse(Agent)` hook
writes validation records; to run Layer-5 on a completed reason run:

```bash
# from Python
from reason.parser import parse_worker_report
from reason.semantic_sampler import check_report, SamplerConfig
# ... see README "Runtime enforcement" section for the full example
```

### 4. Verification

After steps 1-3, run `pytest -q`. All 155+ tests should pass. Then in a
Claude Code session invoke `/reason <non-trivial question>` and check
`~/.reason-logs/<session_id>/validation.jsonl` — you should see one
record per dispatched worker with `grounding_score` > 0.

### What works WITHOUT any of this

- `/reason` slash command with 5 parallel workers
- Structural Layer-1 validator (citations, file existence, line-range bounds)
- PostToolUse(Agent) hook logging to validation.jsonl
- Auto-trigger on matching prompts

Stage-3 rubric scoring in that case falls back to Claude-internal
self-grading — the synthesis still works, but the `degraded: true`
flag will appear in the Grounding-audit footer. For serious use, do
step 1 above at minimum.

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
