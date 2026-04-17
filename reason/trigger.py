"""Pure-logic trigger-phrase matcher. No I/O, no state."""
from dataclasses import dataclass
from typing import Optional
import re

# Ordered by priority: debate triggers checked first so they win ties.
# Longer phrases listed before shorter ones where one is a prefix of another,
# but since we require idx==0 (start-of-prompt), order only matters for
# debate vs default priority separation.
DEBATE_TRIGGERS = (
    "debatuj",
    "debate",
)
DEFAULT_TRIGGERS = (
    "rozważ solidnie",
    "pomyśl porządnie",
    "zastanów się głębiej",
    "jak duży gracz",
    "steelman",
    "deep-think",
    "deep think",
    "reason through",
)
# ??-prefix is special: must be at start of prompt + followed by space
QUESTION_PREFIX = "??"

MIN_QUESTION_CHARS = 20  # non-whitespace chars after the trigger


@dataclass(frozen=True)
class TriggerResult:
    mode: str   # "default" | "debate"
    stripped: str  # the prompt after the trigger removed


def _check_question_length(rest: str) -> bool:
    """Question must have ≥MIN_QUESTION_CHARS non-whitespace characters."""
    return sum(1 for c in rest if not c.isspace()) >= MIN_QUESTION_CHARS


def detect_trigger(prompt: str) -> Optional[TriggerResult]:
    """Scan prompt for a trigger phrase. Return None if no valid trigger found.

    Rules:
    - Case-insensitive match.
    - Debate triggers are checked first (higher priority).
    - ??-prefix must be at start + followed by space + content.
    - After trigger, remaining text must have ≥20 non-whitespace chars.
    """
    if not prompt:
        return None

    lower = prompt.lower()

    # ??-prefix special case
    if prompt.startswith(QUESTION_PREFIX + " "):
        rest = prompt[len(QUESTION_PREFIX) + 1:].strip()
        if _check_question_length(rest):
            return TriggerResult(mode="default", stripped=rest)
        return None

    # Debate triggers (priority)
    for phrase in DEBATE_TRIGGERS:
        if not lower.startswith(phrase):
            continue
        end = len(phrase)
        # Trigger must not bleed into an alphanumeric word (e.g. "debates" must not match "debate")
        right_ok = end == len(prompt) or not prompt[end].isalnum()
        if not right_ok:
            continue
        rest = prompt[end:].strip()
        if _check_question_length(rest):
            return TriggerResult(mode="debate", stripped=rest)

    # Default triggers
    for phrase in DEFAULT_TRIGGERS:
        if not lower.startswith(phrase):
            continue
        end = len(phrase)
        right_ok = end == len(prompt) or not prompt[end].isalnum()
        if not right_ok:
            continue
        rest = prompt[end:].strip()
        if _check_question_length(rest):
            return TriggerResult(mode="default", stripped=rest)

    return None
