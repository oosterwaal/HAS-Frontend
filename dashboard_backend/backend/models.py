"""
Pydantic models for Home Assistant entities and computed values.
"""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class EntityState(BaseModel):
    """Represents a Home Assistant entity state."""
    entity_id: str
    state: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    last_changed: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    context: Optional[dict[str, Any]] = None


class EntityDomain(str, Enum):
    """Common Home Assistant entity domains."""
    LIGHT = "light"
    SWITCH = "switch"
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    CLIMATE = "climate"
    COVER = "cover"
    MEDIA_PLAYER = "media_player"
    AUTOMATION = "automation"
    SCRIPT = "script"
    SCENE = "scene"
    INPUT_BOOLEAN = "input_boolean"
    INPUT_NUMBER = "input_number"
    PERSON = "person"
    DEVICE_TRACKER = "device_tracker"
    WEATHER = "weather"
    FAN = "fan"
    LOCK = "lock"
    VACUUM = "vacuum"


class ComfortScore(BaseModel):
    """Comfort score computed from climate sensors."""
    score: float = Field(ge=0, le=100, description="Overall comfort score 0-100")
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    temperature_score: float = Field(ge=0, le=100, default=50)
    humidity_score: float = Field(ge=0, le=100, default=50)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    factors: dict[str, Any] = Field(default_factory=dict)


class EnergyReading(BaseModel):
    """Energy consumption reading from a sensor."""
    entity_id: str
    value: float
    unit: str = "kWh"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EnergySummary(BaseModel):
    """Aggregated energy consumption data."""
    total_kwh: float = 0.0
    readings: list[EnergyReading] = Field(default_factory=list)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    by_entity: dict[str, float] = Field(default_factory=dict)


class RoomSummary(BaseModel):
    """Summary of entities grouped by room/area."""
    area_id: Optional[str] = None
    area_name: str = "Unknown"
    entities: list[EntityState] = Field(default_factory=list)
    lights_on: int = 0
    lights_total: int = 0
    climate: Optional[dict[str, Any]] = None
    comfort_score: Optional[float] = None


class DashboardState(BaseModel):
    """Complete dashboard state sent to frontend."""
    entities: dict[str, EntityState] = Field(default_factory=dict)
    comfort: Optional[ComfortScore] = None
    energy: Optional[EnergySummary] = None
    rooms: list[RoomSummary] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    connected: bool = False


class ServiceCall(BaseModel):
    """Request to call a Home Assistant service."""
    domain: str
    service: str
    entity_id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class ServiceResponse(BaseModel):
    """Response from a service call."""
    success: bool
    message: str = ""
    data: Optional[Any] = None


class HAMessage(BaseModel):
    """Generic Home Assistant WebSocket message."""
    type: str
    id: Optional[int] = None
    success: Optional[bool] = None
    result: Optional[Any] = None
    event: Optional[dict[str, Any]] = None
    ha_version: Optional[str] = None
    message: Optional[str] = None


class ConnectionStatus(BaseModel):
    """WebSocket connection status."""
    connected: bool = False
    ha_version: Optional[str] = None
    last_event: Optional[datetime] = None
    error: Optional[str] = None
