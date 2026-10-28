from fastapi import APIRouter, Depends
from typing import Any, Dict
from src.api.dependencies import get_meter_service
from src.services.meter_service import MeterService

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Service Health and Status")
def get_health(service: MeterService = Depends(get_meter_service)) -> Dict[str, Any]:
    cache_status = service.get_cache_status()
    portal_ok = service.portal_client.is_authenticated() or cache_status["total_indexed_meters"] > 0
    return {
        "status": "ok",
        "portal_authenticated": service.portal_client.is_authenticated(),
        "portal_connected": portal_ok,
        "cache": cache_status,
    }
