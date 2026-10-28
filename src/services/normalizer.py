from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.models.meter import (
    Meter,
    PhaseType,
    MeterStatus,
    InstallType,
    GeoLocation,
    MeterHierarchy,
    HierarchyNode,
    DistributionTransformer,
)
from src.models.consumption import (
    ConsumptionReading,
    ConsumptionSummary,
    ConsumptionResponse,
)
from src.models.hierarchy import (
    HierarchyAnomaly,
    AnomalyType,
)

# Indian Standard Time offset (+05:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30))


def parse_ist_timestamp_to_utc(ts_str: str) -> Tuple[str, datetime]:
    """Parse Indian Standard Time 'DD/MM/YYYY HH:MM' into ISO-8601 UTC string and datetime object."""
    dt_local = datetime.strptime(ts_str.strip(), "%d/%m/%Y %H:%M").replace(tzinfo=IST_TZ)
    dt_utc = dt_local.astimezone(timezone.utc)
    utc_str = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return utc_str, dt_utc


def normalize_meter(raw: Dict[str, Any]) -> Meter:
    """Normalize a raw meter object from the portal export into the domain model."""
    meter_id = str(raw.get("meterId", "")).strip()
    serial_no = str(raw.get("serialNo", "")).strip()
    make = str(raw.get("make", "Unknown")).strip()

    # Normalize phase
    phase_raw = str(raw.get("phaseType", "single")).lower().strip()
    phase = PhaseType.THREE if "three" in phase_raw else PhaseType.SINGLE

    # Normalize status
    status_raw = str(raw.get("installStatus", "Installed")).strip()
    if "decom" in status_raw.lower():
        status = MeterStatus.DECOMMISSIONED
    elif "fault" in status_raw.lower():
        status = MeterStatus.FAULTY
    else:
        status = MeterStatus.INSTALLED

    # Normalize install type
    itype_raw = str(raw.get("installType", "Whole Current")).strip()
    install_type = InstallType.CT_OPERATED if "ct" in itype_raw.lower() else InstallType.WHOLE_CURRENT

    build_version = str(raw.get("build", "legacy")).strip()
    dt_code = str(raw.get("dtCode", "")).strip()

    # Geo location
    location = None
    geo_raw = raw.get("geo")
    if geo_raw and isinstance(geo_raw, dict):
        try:
            lat = float(geo_raw.get("lat"))
            lng = float(geo_raw.get("lng"))
            location = GeoLocation(latitude=lat, longitude=lng)
        except (TypeError, ValueError):
            location = None

    # Hierarchy
    hierarchy = None
    h_raw = raw.get("hierarchy")
    if h_raw and isinstance(h_raw, dict):
        def parse_node(node_dict: Optional[Dict[str, Any]]) -> Optional[HierarchyNode]:
            if not node_dict or not isinstance(node_dict, dict):
                return None
            code = str(node_dict.get("code", "")).strip()
            name = str(node_dict.get("name", "")).strip()
            return HierarchyNode(code=code, name=name)

        hierarchy = MeterHierarchy(
            zone=parse_node(h_raw.get("zone")),
            circle=parse_node(h_raw.get("circle")),
            division=parse_node(h_raw.get("division")),
            subdivision=parse_node(h_raw.get("subdivision")),
            substation=parse_node(h_raw.get("substation")),
            feeder=parse_node(h_raw.get("feeder")),
            dt=parse_node(h_raw.get("dt")),
        )

    return Meter(
        id=meter_id,
        serial_number=serial_no,
        make=make,
        phase=phase,
        status=status,
        install_type=install_type,
        build_version=build_version,
        dt_code=dt_code,
        location=location,
        hierarchy=hierarchy,
    )


def normalize_dt(raw: Dict[str, Any]) -> DistributionTransformer:
    """Normalize a raw DT object from /portal/dts."""
    code = str(raw.get("code", "")).strip()
    name = str(raw.get("name", "")).strip()
    feeder_code = str(raw.get("feederCode", "")).strip()
    try:
        capacity = float(raw.get("capacityKva", 0.0))
    except (TypeError, ValueError):
        capacity = 0.0

    return DistributionTransformer(
        code=code,
        name=name,
        feeder_code=feeder_code,
        capacity_kva=capacity,
    )


def normalize_readings(
    meter_id: str,
    raw_readings: List[Dict[str, Any]],
    from_time_utc: Optional[str] = None,
    to_time_utc: Optional[str] = None,
    limit: Optional[int] = None,
) -> ConsumptionResponse:
    """Normalize raw energy readings into sorted UTC time series and calculate aggregates."""
    parsed: List[Tuple[datetime, ConsumptionReading]] = []

    for item in raw_readings:
        raw_ts = item.get("timestamp")
        if not raw_ts:
            continue
        try:
            utc_str, dt_utc = parse_ist_timestamp_to_utc(raw_ts)
            kwh = float(item.get("kwh", 0.0))
            kvah = float(item.get("kvah", 0.0))
            volts = float(item.get("voltR", 0.0))
            reading = ConsumptionReading(
                timestamp_utc=utc_str,
                timestamp_local=raw_ts.strip(),
                active_energy_kwh=kwh,
                apparent_energy_kvah=kvah,
                voltage_phase_r_volts=volts,
            )
            parsed.append((dt_utc, reading))
        except (ValueError, TypeError):
            continue

    # Sort chronologically by datetime
    parsed.sort(key=lambda x: x[0])

    # Filter by date range if provided
    dt_from = None
    dt_to = None
    if from_time_utc:
        dt_from = datetime.fromisoformat(from_time_utc.replace("Z", "+00:00"))
    if to_time_utc:
        dt_to = datetime.fromisoformat(to_time_utc.replace("Z", "+00:00"))

    filtered_readings = [
        reading for dt, reading in parsed
        if (dt_from is None or dt >= dt_from) and (dt_to is None or dt <= dt_to)
    ]

    # Apply limit
    if limit is not None and limit > 0:
        filtered_readings = filtered_readings[-limit:]

    # Calculate statistics
    total = len(filtered_readings)
    if total > 0:
        kwh_values = [r.active_energy_kwh for r in filtered_readings]
        volt_values = [r.voltage_phase_r_volts for r in filtered_readings if r.voltage_phase_r_volts > 0]

        min_kwh = min(kwh_values)
        max_kwh = max(kwh_values)
        delta_kwh = round(max_kwh - min_kwh, 2)
        avg_v = round(sum(volt_values) / len(volt_values), 1) if volt_values else None
        earliest = filtered_readings[0].timestamp_utc
        latest = filtered_readings[-1].timestamp_utc
    else:
        min_kwh = max_kwh = delta_kwh = avg_v = earliest = latest = None

    summary = ConsumptionSummary(
        total_readings=total,
        min_kwh=min_kwh,
        max_kwh=max_kwh,
        delta_kwh=delta_kwh,
        average_voltage_volts=avg_v,
        earliest_reading_utc=earliest,
        latest_reading_utc=latest,
    )

    return ConsumptionResponse(
        meter_id=meter_id,
        summary=summary,
        readings=filtered_readings,
    )


def audit_hierarchy(
    meters: List[Meter],
    dt_catalog: Dict[str, DistributionTransformer],
) -> Tuple[List[Meter], List[HierarchyAnomaly]]:
    """Audit hierarchy data for missing codes/names and feeder mismatches, producing reconciled meters and anomaly reports."""
    anomalies: List[HierarchyAnomaly] = []
    reconciled_meters: List[Meter] = []

    # Build reference lookup tables from clean nodes
    feeder_name_to_code: Dict[str, str] = {}
    feeder_code_to_name: Dict[str, str] = {}
    circle_name_to_code: Dict[str, str] = {}
    circle_code_to_name: Dict[str, str] = {}
    substation_name_to_code: Dict[str, str] = {}

    for m in meters:
        if not m.hierarchy:
            continue
        if m.hierarchy.feeder and m.hierarchy.feeder.code and m.hierarchy.feeder.name:
            feeder_name_to_code[m.hierarchy.feeder.name] = m.hierarchy.feeder.code
            feeder_code_to_name[m.hierarchy.feeder.code] = m.hierarchy.feeder.name
        if m.hierarchy.circle and m.hierarchy.circle.code and m.hierarchy.circle.name:
            circle_name_to_code[m.hierarchy.circle.name] = m.hierarchy.circle.code
            circle_code_to_name[m.hierarchy.circle.code] = m.hierarchy.circle.name
        if m.hierarchy.substation and m.hierarchy.substation.code and m.hierarchy.substation.name:
            substation_name_to_code[m.hierarchy.substation.name] = m.hierarchy.substation.code

    for m in meters:
        if not m.hierarchy:
            reconciled_meters.append(m)
            continue

        h = m.hierarchy
        # Check DT code vs hierarchy DT code
        dt_code_meter = m.dt_code
        dt_code_hier = h.dt.code if h.dt else ""
        if dt_code_meter and dt_code_hier and dt_code_meter != dt_code_hier:
            anomalies.append(HierarchyAnomaly(
                meter_id=m.id,
                level="dt",
                anomaly_type=AnomalyType.ORPHAN_METER,
                reported_code=dt_code_hier,
                reported_name=h.dt.name if h.dt else "",
                reconciled_code=dt_code_meter,
                reconciled_name=h.dt.name if h.dt else "",
                message=f"Meter dt_code '{dt_code_meter}' mismatches hierarchy DT '{dt_code_hier}'",
            ))

        # Check feeder against DT catalog
        expected_feeder = dt_catalog.get(m.dt_code).feeder_code if m.dt_code in dt_catalog else None
        feeder_code = h.feeder.code if h.feeder else ""
        feeder_name = h.feeder.name if h.feeder else ""

        if expected_feeder and feeder_code != expected_feeder:
            anomalies.append(HierarchyAnomaly(
                meter_id=m.id,
                level="feeder",
                anomaly_type=AnomalyType.FEEDER_MISMATCH,
                reported_code=feeder_code,
                reported_name=feeder_name,
                reconciled_code=expected_feeder,
                reconciled_name=feeder_code_to_name.get(expected_feeder, feeder_name),
                message=f"Meter feeder '{feeder_code}' mismatches DT {m.dt_code} assigned feeder '{expected_feeder}'",
            ))
            # Reconcile in object
            if h.feeder:
                h.feeder.code = expected_feeder
                if not h.feeder.name and expected_feeder in feeder_code_to_name:
                    h.feeder.name = feeder_code_to_name[expected_feeder]

        # Audit missing codes or names across all levels
        for level_name, node in [
            ("zone", h.zone),
            ("circle", h.circle),
            ("division", h.division),
            ("subdivision", h.subdivision),
            ("substation", h.substation),
            ("feeder", h.feeder),
            ("dt", h.dt),
        ]:
            if not node:
                continue

            if not node.code and node.name:
                reconciled = None
                if level_name == "circle" and node.name in circle_name_to_code:
                    reconciled = circle_name_to_code[node.name]
                elif level_name == "feeder" and node.name in feeder_name_to_code:
                    reconciled = feeder_name_to_code[node.name]
                elif level_name == "substation" and node.name in substation_name_to_code:
                    reconciled = substation_name_to_code[node.name]

                anomalies.append(HierarchyAnomaly(
                    meter_id=m.id,
                    level=level_name,
                    anomaly_type=AnomalyType.EMPTY_CODE,
                    reported_code="",
                    reported_name=node.name,
                    reconciled_code=reconciled,
                    reconciled_name=node.name,
                    message=f"{level_name.capitalize()} has empty code for '{node.name}'. Reconciled: '{reconciled}'",
                ))
                if reconciled:
                    node.code = reconciled

            elif node.code and not node.name:
                reconciled = None
                if level_name == "circle" and node.code in circle_code_to_name:
                    reconciled = circle_code_to_name[node.code]
                elif level_name == "feeder" and node.code in feeder_code_to_name:
                    reconciled = feeder_code_to_name[node.code]

                anomalies.append(HierarchyAnomaly(
                    meter_id=m.id,
                    level=level_name,
                    anomaly_type=AnomalyType.EMPTY_NAME,
                    reported_code=node.code,
                    reported_name="",
                    reconciled_code=node.code,
                    reconciled_name=reconciled,
                    message=f"{level_name.capitalize()} has empty name for '{node.code}'. Reconciled: '{reconciled}'",
                ))
                if reconciled:
                    node.name = reconciled

        reconciled_meters.append(m)

    return reconciled_meters, anomalies
