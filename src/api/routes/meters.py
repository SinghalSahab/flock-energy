from typing import Optional
from fastapi import APIRouter, Depends, Query, Path

from src.api.dependencies import get_meter_service
from src.models.consumption import ConsumptionResponse
from src.models.meter import Meter, MeterListResponse
from src.services.meter_service import MeterService

router = APIRouter(prefix="/meters", tags=["Meters"])


@router.get(
    "",
    response_model=MeterListResponse,
    summary="List and filter smart meters",
    description="Query smart meters with multi-attribute filtering, free-text search, and optional geospatial distance sorting.",
)
def list_meters(
    make: Optional[str] = Query(None, description="Filter by meter manufacturer (e.g., HPL, L&T, Genus, Allied, Secure)"),
    phase: Optional[str] = Query(None, description="Filter by phase configuration: single or three"),
    status: Optional[str] = Query(None, description="Filter by status: Installed, Decommissioned, Faulty"),
    install_type: Optional[str] = Query(None, description="Filter by installation type: Whole Current or CT Operated"),
    dt_code: Optional[str] = Query(None, description="Filter by connected Distribution Transformer code (e.g., DT-001)"),
    feeder_code: Optional[str] = Query(None, description="Filter by upstream Feeder code (e.g., F-001)"),
    q: Optional[str] = Query(None, description="Search term matching meter ID or hardware serial number"),
    near_lat: Optional[float] = Query(None, description="Latitude for spatial proximity search", ge=-90.0, le=90.0),
    near_lng: Optional[float] = Query(None, description="Longitude for spatial proximity search", ge=-180.0, le=180.0),
    radius_km: Optional[float] = Query(None, description="Maximum radius in kilometers from near_lat/near_lng", gt=0),
    limit: int = Query(20, description="Max meters to return per page", ge=1, le=100),
    offset: int = Query(0, description="Pagination offset", ge=0),
    service: MeterService = Depends(get_meter_service),
) -> MeterListResponse:
    return service.query_meters(
        make=make,
        phase=phase,
        status=status,
        install_type=install_type,
        dt_code=dt_code,
        feeder_code=feeder_code,
        q=q,
        near_lat=near_lat,
        near_lng=near_lng,
        radius_km=radius_km,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{id}",
    response_model=Meter,
    summary="Get single meter details",
    description="Retrieve normalized technical specifications, geo location, and network hierarchy for a specific meter.",
)
def get_meter(
    id: str = Path(..., description="Unique meter ID (e.g. J100000)"),
    service: MeterService = Depends(get_meter_service),
) -> Meter:
    return service.get_meter(id)


@router.get(
    "/{id}/consumption",
    response_model=ConsumptionResponse,
    summary="Get meter energy consumption readings",
    description="Retrieve chronological half-hourly consumption readings (kWh, kVAh, Volts) normalized to ISO-8601 UTC with summary statistics.",
)
def get_meter_consumption(
    id: str = Path(..., description="Unique meter ID (e.g. J100000)"),
    from_time: Optional[str] = Query(None, description="Earliest UTC timestamp to include (e.g. 2026-06-25T00:00:00Z)"),
    to_time: Optional[str] = Query(None, description="Latest UTC timestamp to include (e.g. 2026-06-28T23:59:59Z)"),
    limit: Optional[int] = Query(None, description="Maximum readings to return (e.g. 48 for last 24 hours)", ge=1, le=500),
    service: MeterService = Depends(get_meter_service),
) -> ConsumptionResponse:
    return service.get_meter_consumption(
        meter_id=id,
        from_time_utc=from_time,
        to_time_utc=to_time,
        limit=limit,
    )
