"""Trigger-phrase matcher — pure-logic, no I/O."""
import pytest
from reason.trigger import detect_trigger, TriggerResult

# === POSITIVE DEFAULT-MODE MATCHES ===

@pytest.mark.parametrize("prompt,expected_mode,expected_q_prefix", [
    ("rozważ solidnie czy Wojak powinien mieć regime filter sygnały",
     "default", "czy Wojak powinien mieć regime filter sygnały"),
    ("pomyśl porządnie nad tym czy warto uruchomić refactor module X dziś",
     "default", "nad tym czy warto uruchomić refactor module X dziś"),
    ("zastanów się głębiej nad architekturą cache'owania dla RAM-heavy pipeline",
     "default", "nad architekturą cache'owania dla RAM-heavy pipeline"),
    ("jak duży gracz podszedłby do tego problemu skalowania Postgres replikacji",
     "default", "podszedłby do tego problemu skalowania Postgres replikacji"),
    ("steelman this claim: we should migrate all services to Kubernetes right now",
     "default", "this claim: we should migrate all services to Kubernetes right now"),
    ("deep think about whether our cache invalidation strategy actually works",
     "default", "about whether our cache invalidation strategy actually works"),
    ("reason through the consequences of moving to event-sourced architecture",
     "default", "the consequences of moving to event-sourced architecture"),
    ("?? czy warto migrować z SQLite do Postgres dla wielosesyjnego workloadu",
     "default", "czy warto migrować z SQLite do Postgres dla wielosesyjnego workloadu"),
])
def test_default_mode_matches(prompt, expected_mode, expected_q_prefix):
    r = detect_trigger(prompt)
    assert r is not None
    assert r.mode == expected_mode
    assert r.stripped.startswith(expected_q_prefix)

# === DEBATE-MODE MATCHES ===

@pytest.mark.parametrize("prompt", [
    "debatuj czy powinniśmy adoptować LangGraph kosztem własnego orchestratora",
    "debate whether we should adopt LangGraph instead of our home-grown orchestrator",
    "debate this: microservices are always better than monolith for new projects",
])
def test_debate_mode_matches(prompt):
    r = detect_trigger(prompt)
    assert r is not None, f"Expected debate match, got None for: {prompt[:60]}"
    assert r.mode == "debate"

# === NEGATIVE — no match ===

@pytest.mark.parametrize("prompt", [
    "commit all my changes and push please",
    "co to jest fibonacci",  # trigger-like PL but no trigger phrase
    "rozwaz",  # too short, no ≥20 char question follows
    "debatuj",  # just the trigger, no question
    "?? ",  # ??-prefix but empty after
    "??czy to działa",  # no space after ??
    "rozważ solidnie",  # trigger but no question
    "The word steelman appears here mid-sentence as a noun, which is not a trigger.",  # mid-sentence
])
def test_no_match(prompt):
    r = detect_trigger(prompt)
    assert r is None, f"Expected None, got match: {r}"

# === PRIORITY — debate beats default when both present ===

def test_debate_priority():
    r = detect_trigger("debatuj this — also steelman the counter-arguments please, 20+ chars here")
    assert r is not None
    assert r.mode == "debate"

# === CASE INSENSITIVE ===

def test_case_insensitive():
    r = detect_trigger("ROZWAŻ SOLIDNIE czy warto testować case insensitive na tak długim pytaniu")
    assert r is not None
    assert r.mode == "default"
