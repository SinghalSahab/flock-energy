from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class PhaseType(str, Enum):
    SINGLE = "single"
    THREE = "three"


class MeterStatus(str, Enum):
    INSTALLED = "Installed"
    DECOMMISSIONED = "Decommissioned"
    FAULTY = "Faulty"


class InstallType(str, Enum):
    WHOLE_CURRENT = "Whole Current"
    CT_OPERATED = "CT Operated"


class GeoLocation(BaseModel):
    latitude: float = Field(description="Latitude in decimal degrees", ge=-90.0, le=90.0)
    longitude: float = Field(description="Longitude in decimal degrees", ge=-180.0, le=180.0)
    distance_km: Optional[float] = Field(default=None, description="Calculated distance when querying near location")


class HierarchyNode(BaseModel):
    code: str = Field(description="Unique code identifying the network element (e.g., DT-001)")
    name: str = Field(description="Human-readable name of the network element")


class MeterHierarchy(BaseModel):
    zone: Optional[HierarchyNode] = None
    circle: Optional[HierarchyNode] = None
    division: Optional[HierarchyNode] = None
    subdivision: Optional[HierarchyNode] = None
    substation: Optional[HierarchyNode] = None
    feeder: Optional[HierarchyNode] = None
    dt: Optional[HierarchyNode] = None


class Meter(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Unique identifier for the meter (e.g. J100000)")
    serial_number: str = Field(description="Hardware manufacturer serial number")
    make: str = Field(description="Manufacturer make (HPL, L&T, Genus, Allied, Secure)")
    phase: PhaseType = Field(description="Phase configuration: single or three")
    status: MeterStatus = Field(description="Current operational status")
    install_type: InstallType = Field(description="Installation wiring topology")
    build_version: str = Field(description="Legacy firmware/hardware generation (legacy or v2)")
    dt_code: str = Field(description="Distribution transformer code to which this meter is wired")
    location: Optional[GeoLocation] = Field(default=None, description="Geographic coordinate coordinates")
    hierarchy: Optional[MeterHierarchy] = Field(default=None, description="Reconstructed network hierarchy position")


class MeterListResponse(BaseModel):
    items: List[Meter] = Field(description="List of meters matching the query criteria")
    total: int = Field(description="Total number of meters matching query criteria")
    limit: int = Field(description="Maximum results per page")
    offset: int = Field(description="Result offset index")


class DistributionTransformer(BaseModel):
    code: str = Field(description="Unique DT code (e.g. DT-001)")
    name: str = Field(description="Transformer name")
    feeder_code: str = Field(description="Associated 11kV Feeder code")
    capacity_kva: float = Field(description="Rated capacity in kVA")
    meter_count: Optional[int] = Field(default=None, description="Number of downstream meters connected")
