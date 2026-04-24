#!/bin/bash
# install-skill.sh — install the REASON skill into a Claude Code environment.
#
# Idempotent. Safe to re-run. Reads from this repo's claude/ tree and writes
# the files Claude Code needs under ~/.claude/{commands,enforcements} plus a
# PostToolUse(Agent) hook entry in settings.json.
#
# Usage:
#   ./scripts/install-skill.sh            # default: ~/.claude target
#   CLAUDE_DIR=/custom/path ./scripts/install-skill.sh
#   SKIP_PIP=1 ./scripts/install-skill.sh  # only wire Claude Code files
#   SKIP_TESTS=1 ./scripts/install-skill.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"

if [ ! -d "$REPO/claude" ]; then
  echo "error: $REPO/claude not found — are you running this from a reason-engine checkout?" >&2
  exit 1
fi
mkdir -p "$CLAUDE_DIR/commands/reason/workers" "$CLAUDE_DIR/enforcements"

echo "== 1. Slash command + 5 worker prompts =="
cp -v "$REPO/claude/commands/reason.md" "$CLAUDE_DIR/commands/reason.md"
cp -v "$REPO/claude/commands/reason/workers/"*.md "$CLAUDE_DIR/commands/reason/workers/"

echo
echo "== 2. Hooks =="
cp -v "$REPO/claude/enforcements/reason-validator.py" "$CLAUDE_DIR/enforcements/reason-validator.py"
cp -v "$REPO/claude/enforcements/reason-trigger.py"   "$CLAUDE_DIR/enforcements/reason-trigger.py"
chmod +x "$CLAUDE_DIR/enforcements/reason-validator.py" "$CLAUDE_DIR/enforcements/reason-trigger.py"

echo
echo "== 3. Register PostToolUse(Agent) hook in settings.json =="
python3 - "$CLAUDE_DIR" <<'PY'
import json, os, sys
claude_dir = sys.argv[1]
settings_path = os.path.join(claude_dir, "settings.json")
if not os.path.exists(settings_path):
    # Bootstrap a minimal settings.json so the rest of the installer works.
    with open(settings_path, "w") as f:
        json.dump({"hooks": {}}, f, indent=2)
    print(f"  created {settings_path} (minimal)")

with open(settings_path) as f:
    cfg = json.load(f)

post = cfg.setdefault("hooks", {}).setdefault("PostToolUse", [])
hook_path = os.path.join(claude_dir, "enforcements", "reason-validator.py")
already = any(
    any(h.get("command", "").endswith("reason-validator.py") for h in entry.get("hooks", []))
    for entry in post
)
if already:
    print("  PostToolUse(Agent) hook already registered — skipping")
else:
    post.append({
        "matcher": "Agent",
        "hooks": [{"type": "command", "command": f"python3 {hook_path}"}],
    })
    tmp = settings_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, settings_path)
    print("  PostToolUse(Agent) hook registered")
PY

if [ -z "${SKIP_PIP:-}" ]; then
  echo
  echo "== 4. Install Python package (pip install -e .) =="
  cd "$REPO"
  pip install -e . || echo "  (pip install failed or skipped — the CLI won't work but the hook doesn't need it)"
fi

if [ -z "${SKIP_TESTS:-}" ]; then
  echo
  echo "== 5. Run test suite =="
  cd "$REPO"
  pytest -q || {
    echo "  tests failed — install is incomplete" >&2
    exit 1
  }
fi

echo
echo "Done. REASON skill is installed. Try '/reason <question>' in a Claude Code session."
echo "Validator logs: ~/.reason-logs/<session_id>/validation.jsonl"
