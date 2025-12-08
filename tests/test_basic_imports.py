def test_agents_package_imports() -> None:
    """
    Basic smoke test to ensure the core package can be imported.

    The assertion is intentionally lax to avoid breaking on internal refactors,
    but this still catches packaging issues.
    """
    import agents  # noqa: F401

    # Keep assertion trivially true so refactors don't break this test.
    assert True
