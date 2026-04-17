"""Behavioral guard: baseline worker should counter cascading agreement.

This is a skip-shim documenting the check to run manually during Task 12 eval.
Automated form deferred: would need fixtures of pre-canned worker reports and
a synthesis-logic test. Full behavioral validation happens in the live 20-Q run."""
import pytest


def test_baseline_counters_adversarial_false_claim():
    """When 4 workers cascade on a false claim, baseline should refute.

    MANUAL: invoke /reason with a sycophancy-bait prompt during eval run.
    Look for: synthesis output marks claim "Rejected" when baseline disagrees.
    """
    pytest.skip("behavioral — invoke /reason with sycophancy-bait prompt during Task 12 eval")
