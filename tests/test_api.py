import json
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from src.config import Settings
from src.db.repository import SqliteRepository
from src.main import create_app
from src.services.meter_service import MeterService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def get_test_app():
    with open(FIXTURES_DIR / "meter_export_sample.json") as f:
        export_data = json.load(f)["data"]

    with open(FIXTURES_DIR / "dts_page1.json") as f:
        dts_data = json.load(f)["data"]

    with open(FIXTURES_DIR / "meter_energy_sample.json") as f:
        energy_data = json.load(f)["data"]

    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.get_all_distribution_transformers.return_value = dts_data
    mock_client.export_all_meters.return_value = export_data
    mock_client.get_meter_energy.return_value = energy_data

    settings = Settings(
        PORTAL_URL="https://mock-portal.local",
        PORTAL_USERNAME="test@urja.local",
        PORTAL_PASSWORD="mockpassword",
        DB_PATH=":memory:",
        CACHE_TTL_SECONDS=300,
    )

    app = create_app(settings)
    repo = SqliteRepository(":memory:")
    service = MeterService(mock_client, repo, cache_ttl_seconds=300)
    service.sync(force=True)

    app.state.meter_service = service
    app.state.portal_client = mock_client
    return app


def test_api_health():
    app = get_test_app()
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["portal_connected"] is True
    assert "cache" in data


def test_api_list_meters():
    app = get_test_app()
    client = TestClient(app)

    resp = client.get("/meters?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["limit"] == 5
    assert len(data["items"]) == 5
    assert data["total"] == 10

    # Test filtering by make
    resp_make = client.get("/meters?make=HPL")
    assert resp_make.status_code == 200
    for item in resp_make.json()["items"]:
        assert item["make"] == "HPL"


def test_api_get_meter_detail():
    app = get_test_app()
    client = TestClient(app)

    resp = client.get("/meters/J100000")
    assert resp.status_code == 200
    meter = resp.json()
    assert meter["id"] == "J100000"
    assert meter["serial_number"] == "SE33962"
    assert "location" in meter
    assert "hierarchy" in meter


def test_api_get_meter_not_found():
    app = get_test_app()
    client = TestClient(app)

    resp = client.get("/meters/NON_EXISTENT_METER_ID")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "NOT_FOUND"
    assert "not found" in body["error"]["message"].lower()


def test_api_get_meter_consumption():
    app = get_test_app()
    client = TestClient(app)

    resp = client.get("/meters/J100000/consumption?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["meter_id"] == "J100000"
    assert "summary" in data
    assert "readings" in data
    assert len(data["readings"]) == 5
    assert data["readings"][0]["timestamp_utc"].endswith("Z")


def test_api_hierarchy_routes():
    app = get_test_app()
    client = TestClient(app)

    # Hierarchy tree
    resp_tree = client.get("/hierarchy")
    assert resp_tree.status_code == 200
    tree_data = resp_tree.json()
    assert "network_tree" in tree_data
    assert tree_data["total_zones"] > 0

    # Hierarchy anomalies audit
    resp_audit = client.get("/hierarchy/anomalies")
    assert resp_audit.status_code == 200
    audit_data = resp_audit.json()
    assert "anomalies" in audit_data
    assert "total_anomalies_detected" in audit_data


def test_api_cache_refresh():
    app = get_test_app()
    client = TestClient(app)

    resp = client.post("/cache/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_indexed_meters"] == 10
    assert data["is_stale"] is False


def test_api_validation_error():
    app = get_test_app()
    client = TestClient(app)

    # Invalid limit > 100
    resp = client.get("/meters?limit=999")
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "BAD_REQUEST"
