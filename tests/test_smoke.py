"""Project scaffold sanity check — real test, not a tautology."""
import importlib.metadata
import reason


def test_version_matches_package_metadata():
    """__version__ declared in reason/__init__.py must match pyproject.toml."""
    assert reason.__version__ == importlib.metadata.version("reason-engine")
