"""Project scaffold sanity check."""
def test_package_imports():
    import reason
    assert hasattr(reason, "__version__")
