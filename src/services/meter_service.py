from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.db.repository import SqliteRepository
from src.models.consumption import ConsumptionResponse
from src.models.errors import NotFoundError
from src.models.hierarchy import (
    HierarchyAnomaly,
    HierarchyAuditResponse,
    NetworkHierarchyResponse,
    TreeNode,
)
from src.models.meter import DistributionTransformer, Meter, MeterListResponse
from src.services.normalizer import (
    audit_hierarchy,
    normalize_dt,
    normalize_meter,
    normalize_readings,
)
from src.services.portal_client import PortalClient

logger = logging.getLogger("meter_service")


class MeterService:
    """Core domain service coordinating portal synchronization, SQLite indexation,

    hierarchical reconciliation, consumption caching, and query filtering.
    """

    def __init__(
        self,
        portal_client: PortalClient,
        repository: SqliteRepository,
        cache_ttl_seconds: int = 300,
    ):
        self.portal_client = portal_client
        self.repository = repository
        self.cache_ttl_seconds = cache_ttl_seconds

        self._last_sync: float = 0.0
        self._sync_lock = threading.Lock()

        self._dt_catalog: Dict[str, DistributionTransformer] = {}
        self._anomalies: List[HierarchyAnomaly] = []
        self._network_tree: List[TreeNode] = []

        # Cache for meter consumption readings: {meter_id: (timestamp, ConsumptionResponse)}
        self._consumption_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}

    def is_stale(self) -> bool:
        return time.time() - self._last_sync > self.cache_ttl_seconds

    def get_cache_status(self) -> Dict[str, Any]:
        return {
            "last_sync_utc": datetime.fromtimestamp(self._last_sync, tz=timezone.utc).isoformat() if self._last_sync else None,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "age_seconds": round(time.time() - self._last_sync, 1) if self._last_sync else None,
            "is_stale": self.is_stale(),
            "total_indexed_meters": self.repository.count(),
            "total_distribution_transformers": len(self._dt_catalog),
            "total_anomalies_detected": len(self._anomalies),
        }

    def sync(self, force: bool = False) -> Dict[str, Any]:
        """Synchronize meters, DT catalog, and hierarchy from the portal."""
        with self._sync_lock:
            if not force and not self.is_stale() and self._last_sync > 0:
                logger.info("Cache is fresh (age %.1fs). Skipping sync.", time.time() - self._last_sync)
                return self.get_cache_status()

            logger.info("Starting sync from portal...")
            # 1. Fetch DT catalog
            raw_dts = self.portal_client.get_all_distribution_transformers()
            dts = [normalize_dt(item) for item in raw_dts]
            self._dt_catalog = {dt.code: dt for dt in dts}
            logger.info("Loaded %d distribution transformers.", len(self._dt_catalog))

            # 2. Fetch bulk meters
            raw_meters = self.portal_client.export_all_meters()
            normalized_meters = [normalize_meter(raw) for raw in raw_meters]

            # 3. Audit hierarchy and reconcile anomalies
            reconciled_meters, anomalies = audit_hierarchy(normalized_meters, self._dt_catalog)
            self._anomalies = anomalies

            # 4. Upsert into SQLite
            self.repository.upsert_meters(reconciled_meters)

            # 5. Build canonical network hierarchy tree
            self._network_tree = self._build_hierarchy_tree(reconciled_meters)

            self._last_sync = time.time()
            logger.info(
                "Sync complete: %d meters indexed, %d DTs, %d anomalies logged.",
                len(reconciled_meters),
                len(self._dt_catalog),
                len(self._anomalies),
            )
            return self.get_cache_status()

    def ensure_synced(self) -> None:
        if self._last_sync == 0 or self.is_stale():
            self.sync()

    def get_meter(self, meter_id: str) -> Meter:
        self.ensure_synced()
        meter = self.repository.get_by_id(meter_id)
        if not meter:
            raise NotFoundError(f"Meter '{meter_id}' not found.")
        return meter

    def query_meters(
        self,
        make: Optional[str] = None,
        phase: Optional[str] = None,
        status: Optional[str] = None,
        install_type: Optional[str] = None,
        dt_code: Optional[str] = None,
        feeder_code: Optional[str] = None,
        q: Optional[str] = None,
        near_lat: Optional[float] = None,
        near_lng: Optional[float] = None,
        radius_km: Optional[float] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> MeterListResponse:
        self.ensure_synced()
        items, total = self.repository.query_meters(
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
        return MeterListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_meter_consumption(
        self,
        meter_id: str,
        from_time_utc: Optional[str] = None,
        to_time_utc: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> ConsumptionResponse:
        # Check if meter exists
        self.get_meter(meter_id)

        # Check consumption cache (TTL 60s for reading series)
        now = time.time()
        cached = self._consumption_cache.get(meter_id)
        if cached and (now - cached[0] < 60):
            raw_readings = cached[1]
        else:
            raw_readings = self.portal_client.get_meter_energy(meter_id)
            self._consumption_cache[meter_id] = (now, raw_readings)

        return normalize_readings(
            meter_id=meter_id,
            raw_readings=raw_readings,
            from_time_utc=from_time_utc,
            to_time_utc=to_time_utc,
            limit=limit,
        )

    def get_hierarchy_tree(self) -> NetworkHierarchyResponse:
        self.ensure_synced()
        total_substations = len({m.hierarchy.substation.code for m in self._get_all_cached_meters() if m.hierarchy and m.hierarchy.substation})
        total_feeders = len({m.hierarchy.feeder.code for m in self._get_all_cached_meters() if m.hierarchy and m.hierarchy.feeder})

        return NetworkHierarchyResponse(
            network_tree=self._network_tree,
            total_zones=len(self._network_tree),
            total_substations=total_substations,
            total_feeders=total_feeders,
            total_dts=len(self._dt_catalog),
            total_meters=self.repository.count(),
        )

    def get_hierarchy_audit(self) -> HierarchyAuditResponse:
        self.ensure_synced()
        return HierarchyAuditResponse(
            total_meters_audited=self.repository.count(),
            total_anomalies_detected=len(self._anomalies),
            anomalies=self._anomalies,
        )

    def _get_all_cached_meters(self) -> List[Meter]:
        meters, _ = self.repository.query_meters(limit=10000, offset=0)
        return meters

    def _build_hierarchy_tree(self, meters: List[Meter]) -> List[TreeNode]:
        """Construct cascading tree: Zone -> Substation -> Feeder -> DT."""
        zones: Dict[str, TreeNode] = {}
        substations: Dict[str, TreeNode] = {}
        feeders: Dict[str, TreeNode] = {}
        dts: Dict[str, TreeNode] = {}

        for m in meters:
            if not m.hierarchy:
                continue
            h = m.hierarchy

            # Zone
            z_code = h.zone.code if h.zone and h.zone.code else "UNKNOWN_ZONE"
            z_name = h.zone.name if h.zone and h.zone.name else z_code
            if z_code not in zones:
                zones[z_code] = TreeNode(code=z_code, name=z_name, type="zone")
            zones[z_code].meter_count += 1

            # Substation
            ss_code = h.substation.code if h.substation and h.substation.code else "UNKNOWN_SUBSTATION"
            ss_name = h.substation.name if h.substation and h.substation.name else ss_code
            ss_key = f"{z_code}:{ss_code}"
            if ss_key not in substations:
                substations[ss_key] = TreeNode(code=ss_code, name=ss_name, type="substation")
                zones[z_code].children.append(substations[ss_key])
            substations[ss_key].meter_count += 1

            # Feeder
            f_code = h.feeder.code if h.feeder and h.feeder.code else "UNKNOWN_FEEDER"
            f_name = h.feeder.name if h.feeder and h.feeder.name else f_code
            f_key = f"{ss_key}:{f_code}"
            if f_key not in feeders:
                feeders[f_key] = TreeNode(code=f_code, name=f_name, type="feeder")
                substations[ss_key].children.append(feeders[f_key])
            feeders[f_key].meter_count += 1

            # DT
            dt_code = m.dt_code or (h.dt.code if h.dt else "UNKNOWN_DT")
            dt_name = h.dt.name if h.dt and h.dt.name else dt_code
            dt_key = f"{f_key}:{dt_code}"
            if dt_key not in dts:
                dts[dt_key] = TreeNode(code=dt_code, name=dt_name, type="distribution_transformer")
                feeders[f_key].children.append(dts[dt_key])
            dts[dt_key].meter_count += 1

        return list(zones.values())
