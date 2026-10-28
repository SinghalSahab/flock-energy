import json
from pathlib import Path
from src.services.normalizer import (
    normalize_meter,
    normalize_dt,
    normalize_readings,
    audit_hierarchy,
    parse_ist_timestamp_to_utc,
)
from src.models.meter import MeterStatus, PhaseType, InstallType

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_ist_timestamp_to_utc():
    ist_str = "23/06/2026 23:30"
    utc_str, dt_utc = parse_ist_timestamp_to_utc(ist_str)
    # 23:30 IST is 18:00 UTC
    assert utc_str == "2026-06-23T18:00:00Z"
    assert dt_utc.year == 2026
    assert dt_utc.month == 6
    assert dt_utc.day == 23
    assert dt_utc.hour == 18
    assert dt_utc.minute == 0


def test_normalize_meter():
    with open(FIXTURES_DIR / "meter_export_sample.json") as f:
        export_data = json.load(f)

    raw = export_data["data"][0]
    meter = normalize_meter(raw)

    assert meter.id == "J100000"
    assert meter.serial_number == "SE33962"
    assert meter.make == "HPL"
    assert meter.phase == PhaseType.SINGLE
    assert meter.status == MeterStatus.DECOMMISSIONED
    assert meter.install_type == InstallType.WHOLE_CURRENT
    assert meter.dt_code == "DT-001"
    assert meter.location is not None
    assert meter.location.latitude == 26.938961002479868
    assert meter.location.longitude == 75.83095696146852
    assert meter.hierarchy is not None
    assert meter.hierarchy.feeder.code == "F-001"
    assert meter.hierarchy.zone.code == "Z-01"


def test_normalize_dt():
    with open(FIXTURES_DIR / "dts_page1.json") as f:
        dts_data = json.load(f)

    raw = dts_data["data"][0]
    dt = normalize_dt(raw)

    assert dt.code == "DT-001"
    assert dt.name == "Malviya Nagar DT 1"
    assert dt.feeder_code == "F-001"
    assert dt.capacity_kva == 100.0


def test_normalize_readings():
    with open(FIXTURES_DIR / "meter_energy_sample.json") as f:
        energy_data = json.load(f)

    raw_readings = energy_data["data"]
    resp = normalize_readings(
        meter_id="J100000",
        raw_readings=raw_readings,
        limit=5
    )

    assert resp.meter_id == "J100000"
    assert len(resp.readings) == 5
    # First reading should be properly normalized to UTC
    first = resp.readings[0]
    assert first.timestamp_utc.endswith("Z")
    assert first.active_energy_kwh > 0
    assert first.voltage_phase_r_volts > 0

    # Summary statistics should be calculated
    assert resp.summary.total_readings == 5
    assert resp.summary.min_kwh is not None
    assert resp.summary.max_kwh is not None
    assert resp.summary.delta_kwh is not None
    assert resp.summary.average_voltage_volts is not None


def test_audit_hierarchy_anomalies():
    with open(FIXTURES_DIR / "hierarchy_anomalies_sample.json") as f:
        data = json.load(f)

    meters = [normalize_meter(raw) for raw in data["data"]]
    with open(FIXTURES_DIR / "dts_page1.json") as f:
        dts_data = json.load(f)
    dt_catalog = {d["code"]: normalize_dt(d) for d in dts_data["data"]}

    reconciled_meters, anomalies = audit_hierarchy(meters, dt_catalog)
    assert len(anomalies) > 0
    # Check that feeder mismatch or empty code was captured
    anomaly_types = {a.anomaly_type for a in anomalies}
    assert len(anomaly_types) > 0
