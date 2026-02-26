"""
Compute module for aggregation, caching, comfort scores, and energy tracking.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from .models import (
    ComfortScore,
    DashboardState,
    EnergyReading,
    EnergySummary,
    EntityState,
    RoomSummary,
)
from .settings import settings

logger = logging.getLogger(__name__)


class ComputeEngine:
    """Handles all computed values and caching."""
    
    # Comfort score parameters
    IDEAL_TEMP_MIN = 20.0  # °C
    IDEAL_TEMP_MAX = 24.0  # °C
    IDEAL_HUMIDITY_MIN = 40.0  # %
    IDEAL_HUMIDITY_MAX = 60.0  # %
    
    def __init__(self):
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._energy_history: list[EnergyReading] = []
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.utcnow() - timestamp < timedelta(seconds=settings.CACHE_TTL_SECONDS):
                return value
        return None
    
    def _set_cached(self, key: str, value: Any) -> None:
        """Cache a value with timestamp."""
        self._cache[key] = (value, datetime.utcnow())
    
    def invalidate_cache(self, key: Optional[str] = None) -> None:
        """Invalidate cache entry or all cache."""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()
    
    def compute_comfort_score(self, entities: dict[str, EntityState]) -> ComfortScore:
        """
        Compute comfort score from temperature and humidity sensors.
        
        Score is based on:
        - Temperature proximity to ideal range (20-24°C)
        - Humidity proximity to ideal range (40-60%)
        """
        temperatures: list[float] = []
        humidities: list[float] = []
        factors: dict[str, Any] = {}
        
        # Find climate entities
        climate_entities = settings.CLIMATE_ENTITIES or []
        
        for entity_id, entity in entities.items():
            # Check temperature sensors
            if (
                "temperature" in entity_id.lower() or
                entity.attributes.get("device_class") == "temperature" or
                entity_id in climate_entities
            ):
                try:
                    temp = float(entity.state)
                    if -50 < temp < 100:  # Sanity check
                        temperatures.append(temp)
                        factors[f"temp_{entity_id}"] = temp
                except (ValueError, TypeError):
                    pass
            
            # Check humidity sensors
            if (
                "humidity" in entity_id.lower() or
                entity.attributes.get("device_class") == "humidity"
            ):
                try:
                    humidity = float(entity.state)
                    if 0 <= humidity <= 100:
                        humidities.append(humidity)
                        factors[f"humidity_{entity_id}"] = humidity
                except (ValueError, TypeError):
                    pass
            
            # Check climate entities for current temp
            if entity_id.startswith("climate."):
                current_temp = entity.attributes.get("current_temperature")
                current_humidity = entity.attributes.get("current_humidity")
                
                if current_temp:
                    try:
                        temp = float(current_temp)
                        temperatures.append(temp)
                        factors[f"climate_temp_{entity_id}"] = temp
                    except (ValueError, TypeError):
                        pass
                
                if current_humidity:
                    try:
                        humidity = float(current_humidity)
                        humidities.append(humidity)
                        factors[f"climate_humidity_{entity_id}"] = humidity
                    except (ValueError, TypeError):
                        pass
        
        # Calculate average values
        avg_temp = sum(temperatures) / len(temperatures) if temperatures else None
        avg_humidity = sum(humidities) / len(humidities) if humidities else None
        
        # Calculate temperature score (0-100)
        temp_score = 50.0
        if avg_temp is not None:
            if self.IDEAL_TEMP_MIN <= avg_temp <= self.IDEAL_TEMP_MAX:
                temp_score = 100.0
            elif avg_temp < self.IDEAL_TEMP_MIN:
                diff = self.IDEAL_TEMP_MIN - avg_temp
                temp_score = max(0, 100 - (diff * 10))
            else:
                diff = avg_temp - self.IDEAL_TEMP_MAX
                temp_score = max(0, 100 - (diff * 10))
        
        # Calculate humidity score (0-100)
        humidity_score = 50.0
        if avg_humidity is not None:
            if self.IDEAL_HUMIDITY_MIN <= avg_humidity <= self.IDEAL_HUMIDITY_MAX:
                humidity_score = 100.0
            elif avg_humidity < self.IDEAL_HUMIDITY_MIN:
                diff = self.IDEAL_HUMIDITY_MIN - avg_humidity
                humidity_score = max(0, 100 - (diff * 2))
            else:
                diff = avg_humidity - self.IDEAL_HUMIDITY_MAX
                humidity_score = max(0, 100 - (diff * 2))
        
        # Overall score (weighted average)
        overall = (temp_score * 0.6 + humidity_score * 0.4)
        
        return ComfortScore(
            score=round(overall, 1),
            temperature=round(avg_temp, 1) if avg_temp else None,
            humidity=round(avg_humidity, 1) if avg_humidity else None,
            temperature_score=round(temp_score, 1),
            humidity_score=round(humidity_score, 1),
            timestamp=datetime.utcnow(),
            factors=factors
        )
    
    def compute_energy_summary(self, entities: dict[str, EntityState]) -> EnergySummary:
        """
        Compute energy consumption summary from energy sensors.
        """
        readings: list[EnergyReading] = []
        by_entity: dict[str, float] = {}
        total = 0.0
        
        # Find energy entities
        energy_entities = settings.ENERGY_ENTITIES or []
        
        for entity_id, entity in entities.items():
            is_energy = (
                entity_id in energy_entities or
                entity.attributes.get("device_class") == "energy" or
                entity.attributes.get("state_class") == "total_increasing" or
                "energy" in entity_id.lower() or
                "power" in entity_id.lower()
            )
            
            if not is_energy:
                continue
            
            try:
                value = float(entity.state)
                unit = entity.attributes.get("unit_of_measurement", "kWh")
                
                # Convert Wh to kWh
                if unit.lower() == "wh":
                    value = value / 1000
                    unit = "kWh"
                
                reading = EnergyReading(
                    entity_id=entity_id,
                    value=value,
                    unit=unit,
                    timestamp=datetime.utcnow()
                )
                readings.append(reading)
                by_entity[entity_id] = value
                
                # Only sum kWh values for total
                if unit.lower() == "kwh":
                    total += value
                    
            except (ValueError, TypeError):
                pass
        
        # Store in history for tracking
        self._energy_history.extend(readings)
        
        # Keep only last 24 hours of history
        cutoff = datetime.utcnow() - timedelta(hours=24)
        self._energy_history = [
            r for r in self._energy_history if r.timestamp > cutoff
        ]
        
        return EnergySummary(
            total_kwh=round(total, 3),
            readings=readings,
            period_start=cutoff,
            period_end=datetime.utcnow(),
            by_entity=by_entity
        )
    
    def aggregate_by_area(
        self, 
        entities: dict[str, EntityState],
        areas_registry: dict[str, dict] = None,
        entities_registry: dict[str, dict] = None
    ) -> list[RoomSummary]:
        """
        Aggregate entities by room/area using HA registry data.
        """
        areas: dict[str, RoomSummary] = {}
        
        for entity_id, entity in entities.items():
            area_id = None
            area_name = "Unassigned"
            
            # First try registry (most accurate)
            if entities_registry and entity_id in entities_registry:
                reg_area_id = entities_registry[entity_id].get("area_id")
                if reg_area_id and areas_registry and reg_area_id in areas_registry:
                    area_id = reg_area_id
                    area_name = areas_registry[reg_area_id].get("name", "Unknown")
            
            # Fallback: try to extract area from entity_id pattern
            if not area_id:
                parts = entity_id.split(".")
                if len(parts) > 1:
                    name_parts = parts[1].split("_")
                    if len(name_parts) >= 2:
                        potential_area = "_".join(name_parts[:-1])
                        # Check if it matches a known area
                        if areas_registry:
                            for aid, ainfo in areas_registry.items():
                                if potential_area.lower() in ainfo.get("name", "").lower().replace(" ", "_"):
                                    area_id = aid
                                    area_name = ainfo.get("name", "Unknown")
                                    break
            
            if not area_id:
                area_id = "unassigned"
                area_name = "Unassigned"
            
            # Get or create room summary
            if area_id not in areas:
                areas[area_id] = RoomSummary(
                    area_id=area_id,
                    area_name=area_name
                )
            
            room = areas[area_id]
            room.entities.append(entity)
            
            # Count lights
            if entity_id.startswith("light."):
                room.lights_total += 1
                if entity.state == "on":
                    room.lights_on += 1
            
            # Track climate
            if entity_id.startswith("climate."):
                room.climate = {
                    "entity_id": entity_id,
                    "hvac_mode": entity.state,
                    "current_temp": entity.attributes.get("current_temperature"),
                    "target_temp": entity.attributes.get("temperature"),
                }
        
        # Sort by area name, but put Unassigned last
        sorted_areas = sorted(
            areas.values(), 
            key=lambda r: (r.area_id == "unassigned", r.area_name.lower())
        )
        return sorted_areas
    
    def get_cameras(self, entities: dict[str, EntityState]) -> list[dict[str, Any]]:
        """Extract camera entities with their image URLs."""
        cameras = []
        
        for entity_id, entity in entities.items():
            if entity_id.startswith("camera."):
                entity_picture = entity.attributes.get("entity_picture", "")
                cameras.append({
                    "entity_id": entity_id,
                    "name": entity.attributes.get("friendly_name", entity_id.split(".")[-1]),
                    "state": entity.state,
                    "entity_picture": entity_picture,
                    "is_streaming": entity.state in ("streaming", "recording"),
                    "frontend_stream_type": entity.attributes.get("frontend_stream_type"),
                    "supported_features": entity.attributes.get("supported_features", 0)
                })
        
        return sorted(cameras, key=lambda c: c["name"])
    
    def build_dashboard_state(
        self,
        entities: dict[str, EntityState],
        connected: bool,
        areas_registry: dict[str, dict] = None,
        entities_registry: dict[str, dict] = None
    ) -> DashboardState:
        """
        Build complete dashboard state with all computed values.
        """
        # Check cache
        cache_key = f"dashboard_{len(entities)}_{connected}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        # Compute all values
        comfort = self.compute_comfort_score(entities)
        energy = self.compute_energy_summary(entities)
        rooms = self.aggregate_by_area(entities, areas_registry, entities_registry)
        
        # Compute room comfort scores
        for room in rooms:
            room_entities = {e.entity_id: e for e in room.entities}
            room_comfort = self.compute_comfort_score(room_entities)
            room.comfort_score = room_comfort.score
        
        state = DashboardState(
            entities=entities,
            comfort=comfort,
            energy=energy,
            rooms=rooms,
            timestamp=datetime.utcnow(),
            connected=connected
        )
        
        self._set_cached(cache_key, state)
        return state
    
    def get_entity_summary(self, entities: dict[str, EntityState]) -> dict[str, Any]:
        """Get summary counts by domain."""
        summary: dict[str, dict[str, int]] = {}
        
        for entity_id, entity in entities.items():
            domain = entity_id.split(".")[0]
            
            if domain not in summary:
                summary[domain] = {"total": 0, "on": 0, "off": 0, "other": 0}
            
            summary[domain]["total"] += 1
            
            if entity.state == "on":
                summary[domain]["on"] += 1
            elif entity.state == "off":
                summary[domain]["off"] += 1
            else:
                summary[domain]["other"] += 1
        
        return summary


# Singleton instance
compute_engine = ComputeEngine()
