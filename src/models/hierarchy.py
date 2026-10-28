from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AnomalyType(str, Enum):
    EMPTY_CODE = "EMPTY_CODE"
    EMPTY_NAME = "EMPTY_NAME"
    FEEDER_MISMATCH = "FEEDER_MISMATCH"
    ORPHAN_METER = "ORPHAN_METER"


class HierarchyAnomaly(BaseModel):
    meter_id: str = Field(description="Meter ID where anomaly was observed")
    level: str = Field(description="Hierarchy level (zone, circle, division, subdivision, substation, feeder, dt)")
    anomaly_type: AnomalyType = Field(description="Category of anomaly detected")
    reported_code: str = Field(description="Raw code found in portal data")
    reported_name: str = Field(description="Raw name found in portal data")
    reconciled_code: Optional[str] = Field(default=None, description="Inferred/reconciled code from network topology")
    reconciled_name: Optional[str] = Field(default=None, description="Inferred/reconciled name from network topology")
    message: str = Field(description="Explanation of the discrepancy and corrective action taken")


class HierarchyAuditResponse(BaseModel):
    total_meters_audited: int = Field(description="Total meters inspected during hierarchy audit")
    total_anomalies_detected: int = Field(description="Number of anomalies found in raw portal hierarchy")
    anomalies: List[HierarchyAnomaly] = Field(description="Detailed list of all detected anomalies")


class TreeNode(BaseModel):
    code: str
    name: str
    type: str
    children: List["TreeNode"] = Field(default_factory=list)
    meter_count: int = 0


class NetworkHierarchyResponse(BaseModel):
    network_tree: List[TreeNode] = Field(description="Root zones cascading down to feeders, DTs, and meters")
    total_zones: int
    total_substations: int
    total_feeders: int
    total_dts: int
    total_meters: int
