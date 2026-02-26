"""
Diagnostics module for health checks and system monitoring.
"""
import logging
import platform
import sys
from datetime import datetime
from typing import Any, Optional

from .ha_rest import ha_rest
from .ha_ws import ha_client
from .settings import settings

logger = logging.getLogger(__name__)


class Diagnostics:
    """System diagnostics and health checks."""
    
    def __init__(self):
        self.start_time: datetime = datetime.utcnow()
    
    @property
    def uptime_seconds(self) -> float:
        """Get uptime in seconds."""
        return (datetime.utcnow() - self.start_time).total_seconds()
    
    async def check_ha_connection(self) -> dict[str, Any]:
        """Check Home Assistant connectivity."""
        result = {
            "websocket": {
                "connected": ha_client.status.connected,
                "ha_version": ha_client.status.ha_version,
                "last_event": ha_client.status.last_event.isoformat() if ha_client.status.last_event else None,
                "error": ha_client.status.error,
                "entity_count": len(ha_client.states)
            },
            "rest_api": {
                "accessible": False,
                "message": None
            }
        }
        
        # Test REST API
        accessible, message = await ha_rest.check_api()
        result["rest_api"]["accessible"] = accessible
        result["rest_api"]["message"] = message
        
        return result
    
    def check_settings(self) -> dict[str, Any]:
        """Check settings configuration."""
        valid, error = settings.validate()
        
        return {
            "valid": valid,
            "error": error,
            "ha_url": settings.HA_URL,
            "ha_token_set": bool(settings.HA_TOKEN),
            "host": settings.HOST,
            "port": settings.PORT,
            "cache_ttl": settings.CACHE_TTL_SECONDS,
            "energy_entities": len(settings.ENERGY_ENTITIES),
            "climate_entities": len(settings.CLIMATE_ENTITIES),
            "subscribe_domains": settings.SUBSCRIBE_DOMAINS or ["all"]
        }
    
    def get_system_info(self) -> dict[str, Any]:
        """Get system information."""
        return {
            "python_version": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "uptime_seconds": round(self.uptime_seconds, 2),
            "start_time": self.start_time.isoformat()
        }
    
    async def get_full_diagnostics(self) -> dict[str, Any]:
        """Get complete diagnostics report."""
        ha_status = await self.check_ha_connection()
        
        return {
            "status": "healthy" if ha_status["websocket"]["connected"] else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "system": self.get_system_info(),
            "settings": self.check_settings(),
            "home_assistant": ha_status,
            "health_checks": {
                "websocket_connected": ha_status["websocket"]["connected"],
                "rest_api_accessible": ha_status["rest_api"]["accessible"],
                "settings_valid": self.check_settings()["valid"],
                "entities_loaded": ha_status["websocket"]["entity_count"] > 0
            }
        }
    
    async def health_check(self) -> tuple[bool, str]:
        """
        Simple health check for load balancers/monitors.
        Returns (healthy, message).
        """
        # Check WebSocket connection
        if not ha_client.status.connected:
            return False, "WebSocket disconnected"
        
        # Check if we have entities
        if len(ha_client.states) == 0:
            return False, "No entities loaded"
        
        return True, "OK"


# Singleton instance
diagnostics = Diagnostics()
