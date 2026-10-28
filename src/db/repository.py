import json
import math
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from src.models.meter import Meter, GeoLocation


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 999999.0
    r = 6371.0  # Earth's radius in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


class SqliteRepository:
    """SQLite-backed index enabling high-performance cross-attribute filtering and spatial queries."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Register custom Haversine function for geospatial SQL queries
        conn.create_function("haversine_km", 4, haversine_distance_km)
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meters (
                    id TEXT PRIMARY KEY,
                    serial_number TEXT,
                    make TEXT,
                    phase TEXT,
                    status TEXT,
                    install_type TEXT,
                    build_version TEXT,
                    dt_code TEXT,
                    feeder_code TEXT,
                    substation_code TEXT,
                    zone_code TEXT,
                    latitude REAL,
                    longitude REAL,
                    raw_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meters_make ON meters(make)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meters_phase ON meters(phase)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meters_status ON meters(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meters_dt ON meters(dt_code)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meters_feeder ON meters(feeder_code)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meters_coords ON meters(latitude, longitude)")

    def upsert_meters(self, meters: List[Meter]) -> None:
        """Batch upsert normalized meters into the SQLite index."""
        with self._get_connection() as conn:
            records = []
            for m in meters:
                lat = m.location.latitude if m.location else None
                lng = m.location.longitude if m.location else None
                feeder = m.hierarchy.feeder.code if m.hierarchy and m.hierarchy.feeder else None
                substation = m.hierarchy.substation.code if m.hierarchy and m.hierarchy.substation else None
                zone = m.hierarchy.zone.code if m.hierarchy and m.hierarchy.zone else None

                records.append((
                    m.id,
                    m.serial_number,
                    m.make,
                    m.phase.value,
                    m.status.value,
                    m.install_type.value,
                    m.build_version,
                    m.dt_code,
                    feeder,
                    substation,
                    zone,
                    lat,
                    lng,
                    m.model_dump_json()
                ))

            conn.executemany("""
                INSERT OR REPLACE INTO meters (
                    id, serial_number, make, phase, status, install_type,
                    build_version, dt_code, feeder_code, substation_code,
                    zone_code, latitude, longitude, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)

    def get_by_id(self, meter_id: str) -> Optional[Meter]:
        """Fetch single meter by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT raw_json FROM meters WHERE id = ?", (meter_id,)).fetchone()
            if not row:
                return None
            return Meter.model_validate_json(row["raw_json"])

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
    ) -> Tuple[List[Meter], int]:
        """Query meters with multi-attribute filtering, search, and optional geospatial distance."""
        conditions = []
        params: List[Any] = []

        if make:
            conditions.append("LOWER(make) = LOWER(?)")
            params.append(make)
        if phase:
            conditions.append("LOWER(phase) = LOWER(?)")
            params.append(phase)
        if status:
            conditions.append("LOWER(status) = LOWER(?)")
            params.append(status)
        if install_type:
            conditions.append("LOWER(install_type) = LOWER(?)")
            params.append(install_type)
        if dt_code:
            conditions.append("UPPER(dt_code) = UPPER(?)")
            params.append(dt_code)
        if feeder_code:
            conditions.append("UPPER(feeder_code) = UPPER(?)")
            params.append(feeder_code)

        if q:
            term = f"%{q.strip()}%"
            conditions.append("(id LIKE ? OR serial_number LIKE ? OR make LIKE ? OR dt_code LIKE ?)")
            params.extend([term, term, term, term])

        # Geospatial filtering
        is_geo = near_lat is not None and near_lng is not None
        if is_geo:
            conditions.append("latitude IS NOT NULL AND longitude IS NOT NULL")
            if radius_km is not None and radius_km > 0:
                conditions.append("haversine_km(latitude, longitude, ?, ?) <= ?")
                params.extend([near_lat, near_lng, radius_km])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"SELECT COUNT(*) as cnt FROM meters {where_clause}"

        with self._get_connection() as conn:
            # Get total matching count
            total = conn.execute(count_sql, params).fetchone()["cnt"]

            # Select data
            if is_geo:
                select_sql = f"""
                    SELECT raw_json, haversine_km(latitude, longitude, ?, ?) as distance_km
                    FROM meters
                    {where_clause}
                    ORDER BY distance_km ASC
                    LIMIT ? OFFSET ?
                """
                query_params = [near_lat, near_lng] + params + [limit, offset]
                rows = conn.execute(select_sql, query_params).fetchall()
                meters = []
                for r in rows:
                    m = Meter.model_validate_json(r["raw_json"])
                    if m.location:
                        m.location.distance_km = round(float(r["distance_km"]), 2)
                    meters.append(m)
                return meters, total
            else:
                select_sql = f"""
                    SELECT raw_json
                    FROM meters
                    {where_clause}
                    ORDER BY id ASC
                    LIMIT ? OFFSET ?
                """
                query_params = params + [limit, offset]
                rows = conn.execute(select_sql, query_params).fetchall()
                meters = [Meter.model_validate_json(r["raw_json"]) for r in rows]
                return meters, total

    def count(self) -> int:
        with self._get_connection() as conn:
            return conn.execute("SELECT COUNT(*) as cnt FROM meters").fetchone()["cnt"]
