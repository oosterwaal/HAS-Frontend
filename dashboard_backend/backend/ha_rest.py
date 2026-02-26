"""
Home Assistant REST API client for service calls and state queries.

Docs: https://developers.home-assistant.io/docs/api/rest
"""
import logging
from typing import Any, Optional

import aiohttp

from .models import EntityState, ServiceCall, ServiceResponse
from .settings import settings

logger = logging.getLogger(__name__)


class HARestClient:
    """REST API client for Home Assistant."""
    
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def _headers(self) -> dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {settings.HA_TOKEN}",
            "Content-Type": "application/json"
        }
    
    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session
    
    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def get_state(self, entity_id: str) -> Optional[EntityState]:
        """
        Get current state of an entity.
        
        GET /api/states/<entity_id>
        """
        session = await self._ensure_session()
        url = f"{settings.HA_URL}/api/states/{entity_id}"
        
        try:
            async with session.get(url, headers=self._headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return EntityState(
                        entity_id=data["entity_id"],
                        state=data.get("state", "unknown"),
                        attributes=data.get("attributes", {}),
                        last_changed=data.get("last_changed"),
                        last_updated=data.get("last_updated"),
                        context=data.get("context")
                    )
                elif resp.status == 404:
                    logger.warning(f"Entity not found: {entity_id}")
                else:
                    logger.error(f"Failed to get state: {resp.status}")
        except Exception as e:
            logger.error(f"Error getting state for {entity_id}: {e}")
        
        return None
    
    async def get_states(self) -> list[EntityState]:
        """
        Get all entity states.
        
        GET /api/states
        """
        session = await self._ensure_session()
        url = f"{settings.HA_URL}/api/states"
        
        try:
            async with session.get(url, headers=self._headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [
                        EntityState(
                            entity_id=e["entity_id"],
                            state=e.get("state", "unknown"),
                            attributes=e.get("attributes", {}),
                            last_changed=e.get("last_changed"),
                            last_updated=e.get("last_updated"),
                            context=e.get("context")
                        )
                        for e in data
                    ]
                else:
                    logger.error(f"Failed to get states: {resp.status}")
        except Exception as e:
            logger.error(f"Error getting states: {e}")
        
        return []
    
    async def call_service(self, call: ServiceCall) -> ServiceResponse:
        """
        Call a Home Assistant service.
        
        POST /api/services/<domain>/<service>
        """
        session = await self._ensure_session()
        url = f"{settings.HA_URL}/api/services/{call.domain}/{call.service}"
        
        # Build request data
        data: dict[str, Any] = {}
        if call.entity_id:
            data["entity_id"] = call.entity_id
        data.update(call.data)
        
        try:
            async with session.post(url, headers=self._headers, json=data) as resp:
                response_data = None
                try:
                    response_data = await resp.json()
                except Exception:
                    pass
                
                if resp.status == 200:
                    logger.info(f"Service called: {call.domain}.{call.service}")
                    return ServiceResponse(
                        success=True,
                        message="Service called successfully",
                        data=response_data
                    )
                else:
                    error = response_data.get("message", f"HTTP {resp.status}") if response_data else f"HTTP {resp.status}"
                    logger.error(f"Service call failed: {error}")
                    return ServiceResponse(
                        success=False,
                        message=error
                    )
        except Exception as e:
            logger.error(f"Error calling service: {e}")
            return ServiceResponse(
                success=False,
                message=str(e)
            )
    
    async def turn_on(self, entity_id: str, **kwargs) -> ServiceResponse:
        """Turn on an entity."""
        domain = entity_id.split(".")[0]
        return await self.call_service(ServiceCall(
            domain=domain,
            service="turn_on",
            entity_id=entity_id,
            data=kwargs
        ))
    
    async def turn_off(self, entity_id: str) -> ServiceResponse:
        """Turn off an entity."""
        domain = entity_id.split(".")[0]
        return await self.call_service(ServiceCall(
            domain=domain,
            service="turn_off",
            entity_id=entity_id
        ))
    
    async def toggle(self, entity_id: str) -> ServiceResponse:
        """Toggle an entity."""
        domain = entity_id.split(".")[0]
        return await self.call_service(ServiceCall(
            domain=domain,
            service="toggle",
            entity_id=entity_id
        ))
    
    async def set_hvac_mode(self, entity_id: str, hvac_mode: str) -> ServiceResponse:
        """Set HVAC mode for a climate entity."""
        return await self.call_service(ServiceCall(
            domain="climate",
            service="set_hvac_mode",
            entity_id=entity_id,
            data={"hvac_mode": hvac_mode}
        ))
    
    async def set_temperature(self, entity_id: str, temperature: float) -> ServiceResponse:
        """Set target temperature for a climate entity."""
        return await self.call_service(ServiceCall(
            domain="climate",
            service="set_temperature",
            entity_id=entity_id,
            data={"temperature": temperature}
        ))
    
    async def check_api(self) -> tuple[bool, Optional[str]]:
        """
        Check if the API is accessible.
        
        GET /api/
        """
        session = await self._ensure_session()
        url = f"{settings.HA_URL}/api/"
        
        try:
            async with session.get(url, headers=self._headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return True, data.get("message", "API running")
                else:
                    return False, f"HTTP {resp.status}"
        except Exception as e:
            return False, str(e)
    
    async def get_config(self) -> Optional[dict[str, Any]]:
        """
        Get Home Assistant configuration.
        
        GET /api/config
        """
        session = await self._ensure_session()
        url = f"{settings.HA_URL}/api/config"
        
        try:
            async with session.get(url, headers=self._headers) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.error(f"Error getting config: {e}")
        
        return None
    
    async def get_history(
        self,
        entity_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        Get history for an entity.
        
        GET /api/history/period/<timestamp>?filter_entity_id=<entity_id>
        """
        session = await self._ensure_session()
        
        # Build URL
        if start_time:
            url = f"{settings.HA_URL}/api/history/period/{start_time}"
        else:
            url = f"{settings.HA_URL}/api/history/period"
        
        params = {"filter_entity_id": entity_id}
        if end_time:
            params["end_time"] = end_time
        
        try:
            async with session.get(url, headers=self._headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data[0] if data else []
        except Exception as e:
            logger.error(f"Error getting history: {e}")
        
        return []


# Singleton instance
ha_rest = HARestClient()
