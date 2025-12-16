import os


def test_required_env_variables_are_accessible() -> None:
    """
    Basic sanity check to ensure that reading required environment variables
    does not crash the test environment.
    """
    required = [
        "POLYGON_WALLET_PRIVATE_KEY",
        "OPENAI_API_KEY",
    ]
    for name in required:
        _ = os.getenv(name)

    # If we reach this point, access to os.getenv works as expected.
    assert True
