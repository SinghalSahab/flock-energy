from typing import Any, Dict
from fastapi import APIRouter, Depends

from src.api.dependencies import get_meter_service
from src.services.meter_service import MeterService

router = APIRouter(prefix="/cache", tags=["Cache"])


@router.get(
    "",
    summary="Inspect cache staleness and indexing statistics",
)
def get_cache_status(service: MeterService = Depends(get_meter_service)) -> Dict[str, Any]:
    return service.get_cache_status()


@router.post(
    "/refresh",
    summary="Force refresh local cache from portal",
    description="Trigger an immediate re-synchronization with the Urja Meter Ops portal via bulk cryptographic export.",
)
def refresh_cache(service: MeterService = Depends(get_meter_service)) -> Dict[str, Any]:
    return service.sync(force=True)
