def test_package_imports():
    """The engine is importable under its post-`P2.1` name and knows its version."""
    from engines import t2pbi

    assert t2pbi.__version__
