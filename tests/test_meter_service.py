import json
from pathlib import Path
from unittest.mock import MagicMock

from src.db.repository import SqliteRepository
from src.services.meter_service import MeterService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def create_test_service():
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

    repo = SqliteRepository(":memory:")
    service = MeterService(
        portal_client=mock_client,
        repository=repo,
        cache_ttl_seconds=300,
    )
    return service, mock_client


def test_service_sync_and_query():
    service, mock_client = create_test_service()

    # Initial query should trigger sync
    res = service.query_meters(limit=10)
    assert res.total == 10
    assert len(res.items) == 10
    assert mock_client.export_all_meters.call_count == 1

    # Second query within TTL should NOT hit portal again
    res2 = service.query_meters(limit=5)
    assert res2.total == 10
    assert len(res2.items) == 5
    assert mock_client.export_all_meters.call_count == 1


def test_service_filtering():
    service, _ = create_test_service()
    service.sync(force=True)

    # Filter by make
    res_make = service.query_meters(make="HPL")
    for m in res_make.items:
        assert m.make == "HPL"

    # Filter by phase
    res_phase = service.query_meters(phase="single")
    for m in res_phase.items:
        assert m.phase.value == "single"

    # Search term
    res_q = service.query_meters(q="J100000")
    assert res_q.total == 1
    assert res_q.items[0].id == "J100000"


def test_service_spatial_proximity():
    service, _ = create_test_service()
    service.sync(force=True)

    # Query near Malviya Nagar coordinates (lat 26.9389, lng 75.8309)
    res_near = service.query_meters(
        near_lat=26.9389,
        near_lng=75.8309,
        radius_km=50.0,
        limit=5,
    )
    assert len(res_near.items) > 0
    # Items should be ordered by distance_km
    for m in res_near.items:
        assert m.location is not None
        assert m.location.distance_km is not None
        assert m.location.distance_km <= 50.0


def test_service_hierarchy_tree_and_audit():
    service, _ = create_test_service()
    service.sync(force=True)

    tree = service.get_hierarchy_tree()
    assert tree.total_zones > 0
    assert len(tree.network_tree) > 0

    audit = service.get_hierarchy_audit()
    assert audit.total_meters_audited == 10
