def test_basic_imports() -> None:
    """
    Sanity test that imports the top-level package.

    This helps catch packaging issues early in CI.
    """
    try:
        import agents  # type: ignore  # noqa: F401
    except Exception as exc:  # pragma: no cover
        raise AssertionError(f"Failed to import 'agents' package: {exc}")
