from typing import List, Optional
from pydantic import BaseModel, Field


class ConsumptionReading(BaseModel):
    timestamp_utc: str = Field(description="Normalized ISO-8601 UTC timestamp (e.g. 2026-06-23T18:00:00Z)")
    timestamp_local: str = Field(description="Original local timestamp from the meter (DD/MM/YYYY HH:MM, IST +05:30)")
    active_energy_kwh: float = Field(description="Cumulative active energy registered in kilowatt-hours (kWh)")
    apparent_energy_kvah: float = Field(description="Cumulative apparent energy in kilovolt-ampere-hours (kVAh)")
    voltage_phase_r_volts: float = Field(description="R-phase voltage in Volts (V)")


class ConsumptionSummary(BaseModel):
    total_readings: int = Field(description="Number of reading intervals returned")
    min_kwh: Optional[float] = Field(default=None, description="Minimum recorded cumulative kWh in interval")
    max_kwh: Optional[float] = Field(default=None, description="Maximum recorded cumulative kWh in interval")
    delta_kwh: Optional[float] = Field(default=None, description="Net consumption registered across interval (max - min)")
    average_voltage_volts: Optional[float] = Field(default=None, description="Average R-phase voltage across interval")
    earliest_reading_utc: Optional[str] = Field(default=None, description="UTC timestamp of the first reading in window")
    latest_reading_utc: Optional[str] = Field(default=None, description="UTC timestamp of the last reading in window")


class ConsumptionResponse(BaseModel):
    meter_id: str = Field(description="Target meter identifier")
    summary: ConsumptionSummary = Field(description="Statistical aggregate summary across the requested window")
    readings: List[ConsumptionReading] = Field(description="Chronological series of consumption readings")
