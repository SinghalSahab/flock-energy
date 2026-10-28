from fastapi import APIRouter, Depends

from src.api.dependencies import get_meter_service
from src.models.hierarchy import HierarchyAuditResponse, NetworkHierarchyResponse
from src.services.meter_service import MeterService

router = APIRouter(prefix="/hierarchy", tags=["Hierarchy"])


@router.get(
    "",
    response_model=NetworkHierarchyResponse,
    summary="Get reconstructed network hierarchy tree",
    description="Retrieve canonical electrical network tree cascading from Zones to Substations, Feeders, DTs, and downstream meters.",
)
def get_network_hierarchy(
    service: MeterService = Depends(get_meter_service),
) -> NetworkHierarchyResponse:
    return service.get_hierarchy_tree()


@router.get(
    "/anomalies",
    response_model=HierarchyAuditResponse,
    summary="Audit network hierarchy data anomalies",
    description="Inspect all detected hierarchy data anomalies (empty codes, empty names, feeder mismatches) along with reconciled canonical values.",
)
def get_hierarchy_anomalies(
    service: MeterService = Depends(get_meter_service),
) -> HierarchyAuditResponse:
    return service.get_hierarchy_audit()
