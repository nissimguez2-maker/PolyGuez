import importlib


def test_webhook_server_fastapi_importable() -> None:
    """Regression test: requirements must include FastAPI for app import."""
    module = importlib.import_module("webhook_server_fastapi")
    assert hasattr(module, "app")
