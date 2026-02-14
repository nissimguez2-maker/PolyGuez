from fastapi.testclient import TestClient


def test_market_data_health_endpoint_works_without_startup():
    from webhook_server_fastapi import app
    # register health routes into app (no startup side-effects)
    from src.market_data.health_routes import register
    register(app)
    # Prevent startup/shutdown side effects (WS connect) in this test
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    with TestClient(app) as client:
        r = client.get("/market-data/health")
        assert r.status_code == 200
        data = r.json()

        for k in [
            "ok",
            "ws_connected",
            "last_msg_age_s",
            "active_subscriptions",
            "stale_tokens",
            "eventbus_dropped_total",
            "notes",
        ]:
            assert k in data


def test_market_data_metrics_endpoint_returns_json():
    from webhook_server_fastapi import app

    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    with TestClient(app) as client:
        r = client.get("/market-data/metrics")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

