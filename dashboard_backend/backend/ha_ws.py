"""
Home Assistant WebSocket client for live state updates.

Implements the HA WebSocket API protocol:
1. Connect to ws://<ha_url>/api/websocket
2. Receive auth_required message
3. Send auth message with access token
4. Receive auth_ok or auth_invalid
5. Subscribe to state_changed events
6. Process incoming events

Docs: https://developers.home-assistant.io/docs/api/websocket
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .models import ConnectionStatus, EntityState, HAMessage
from .settings import settings

logger = logging.getLogger(__name__)


class HAWebSocketClient:
    """WebSocket client for Home Assistant real-time updates."""
    
    def __init__(self):
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._message_id: int = 0
        self._running: bool = False
        self._reconnect_delay: float = 5.0
        self._max_reconnect_delay: float = 60.0
        
        # State storage
        self.states: dict[str, EntityState] = {}
        self.status = ConnectionStatus()
        
        # Registry storage
        self.areas: dict[str, dict[str, Any]] = {}  # area_id -> {name, ...}
        self.devices: dict[str, dict[str, Any]] = {}  # device_id -> {area_id, ...}
        self.entities_registry: dict[str, dict[str, Any]] = {}  # entity_id -> {device_id, area_id, ...}
        
        # Callbacks
        self._on_state_change: Optional[Callable[[EntityState], None]] = None
        self._on_connect: Optional[Callable[[], None]] = None
        self._on_disconnect: Optional[Callable[[Optional[str]], None]] = None
        
        # Pending requests
        self._pending: dict[int, asyncio.Future] = {}
    
    def _next_id(self) -> int:
        """Get next message ID."""
        self._message_id += 1
        return self._message_id
    
    def on_state_change(self, callback: Callable[[EntityState], None]) -> None:
        """Register callback for state changes."""
        self._on_state_change = callback
    
    def on_connect(self, callback: Callable[[], None]) -> None:
        """Register callback for successful connection."""
        self._on_connect = callback
    
    def on_disconnect(self, callback: Callable[[Optional[str]], None]) -> None:
        """Register callback for disconnection."""
        self._on_disconnect = callback
    
    async def _send(self, message: dict[str, Any]) -> None:
        """Send a message to Home Assistant."""
        if self._ws:
            await self._ws.send(json.dumps(message))
    
    async def _send_and_wait(self, message: dict[str, Any], timeout: float = 10.0) -> HAMessage:
        """Send a message and wait for response."""
        msg_id = message.get("id", self._next_id())
        message["id"] = msg_id
        
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future
        
        try:
            await self._send(message)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        finally:
            self._pending.pop(msg_id, None)
    
    async def _authenticate(self) -> bool:
        """Authenticate with Home Assistant."""
        if not self._ws:
            return False
        
        # Wait for auth_required message
        msg = await self._ws.recv()
        data = json.loads(msg)
        
        if data.get("type") != "auth_required":
            logger.error(f"Expected auth_required, got: {data.get('type')}")
            return False
        
        # Send auth message
        await self._send({
            "type": "auth",
            "access_token": settings.HA_TOKEN
        })
        
        # Wait for auth response
        msg = await self._ws.recv()
        data = json.loads(msg)
        
        if data.get("type") == "auth_ok":
            self.status.ha_version = data.get("ha_version")
            self.status.connected = True
            self.status.error = None
            logger.info(f"Authenticated with HA {self.status.ha_version}")
            return True
        else:
            error = data.get("message", "Authentication failed")
            self.status.error = error
            logger.error(f"Auth failed: {error}")
            return False
    
    async def _subscribe_events(self) -> bool:
        """Subscribe to state_changed events."""
        msg_id = self._next_id()
        await self._send({
            "id": msg_id,
            "type": "subscribe_events",
            "event_type": "state_changed"
        })
        
        # Wait for subscription confirmation
        msg = await self._ws.recv()
        data = json.loads(msg)
        
        if data.get("success"):
            logger.info("Subscribed to state_changed events")
            return True
        else:
            logger.error(f"Failed to subscribe: {data}")
            return False
    
    async def _fetch_states(self) -> bool:
        """Fetch all current states."""
        try:
            msg_id = self._next_id()
            await self._send({
                "id": msg_id,
                "type": "get_states"
            })
            
            # Receive response directly (not through message loop)
            msg = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
            data = json.loads(msg)
            
            if data.get("id") == msg_id and data.get("success") and data.get("result"):
                for state_data in data["result"]:
                    entity = self._parse_entity_state(state_data)
                    if entity:
                        self.states[entity.entity_id] = entity
                logger.info(f"Fetched {len(self.states)} entity states")
                return True
            else:
                logger.error(f"Unexpected response for get_states: {data.get('type')}")
        except asyncio.TimeoutError:
            logger.error("Timeout fetching states")
        except Exception as e:
            logger.error(f"Failed to fetch states: {e}")
        return False
    
    async def _fetch_registry(self, registry_type: str) -> list[dict[str, Any]]:
        """Fetch a registry (areas, devices, entities) from HA."""
        try:
            msg_id = self._next_id()
            await self._send({
                "id": msg_id,
                "type": f"config/{registry_type}/list"
            })
            
            msg = await asyncio.wait_for(self._ws.recv(), timeout=15.0)
            data = json.loads(msg)
            
            if data.get("id") == msg_id and data.get("success"):
                return data.get("result", [])
        except Exception as e:
            logger.error(f"Failed to fetch {registry_type} registry: {e}")
        return []
    
    async def _fetch_registries(self) -> None:
        """Fetch all registries to map entities to areas."""
        # Fetch area registry
        areas = await self._fetch_registry("area_registry")
        for area in areas:
            self.areas[area["area_id"]] = {
                "name": area.get("name", "Unknown"),
                "area_id": area["area_id"],
                "aliases": area.get("aliases", []),
                "picture": area.get("picture")
            }
        logger.info(f"Fetched {len(self.areas)} areas")
        
        # Fetch device registry
        devices = await self._fetch_registry("device_registry")
        for device in devices:
            self.devices[device["id"]] = {
                "area_id": device.get("area_id"),
                "name": device.get("name_by_user") or device.get("name", "Unknown"),
                "manufacturer": device.get("manufacturer"),
                "model": device.get("model")
            }
        logger.info(f"Fetched {len(self.devices)} devices")
        
        # Fetch entity registry
        entities = await self._fetch_registry("entity_registry")
        for entity in entities:
            entity_id = entity.get("entity_id")
            if entity_id:
                device_id = entity.get("device_id")
                # Entity can have direct area_id or inherit from device
                area_id = entity.get("area_id")
                if not area_id and device_id and device_id in self.devices:
                    area_id = self.devices[device_id].get("area_id")
                
                self.entities_registry[entity_id] = {
                    "area_id": area_id,
                    "device_id": device_id,
                    "name": entity.get("name") or entity.get("original_name"),
                    "platform": entity.get("platform"),
                    "disabled_by": entity.get("disabled_by")
                }
        logger.info(f"Fetched {len(self.entities_registry)} entity registry entries")
    
    def get_entity_area(self, entity_id: str) -> Optional[dict[str, Any]]:
        """Get area info for an entity."""
        reg = self.entities_registry.get(entity_id, {})
        area_id = reg.get("area_id")
        if area_id and area_id in self.areas:
            return self.areas[area_id]
        return None
    
    def _parse_entity_state(self, data: dict[str, Any]) -> Optional[EntityState]:
        """Parse entity state from HA message."""
        try:
            return EntityState(
                entity_id=data["entity_id"],
                state=data.get("state", "unknown"),
                attributes=data.get("attributes", {}),
                last_changed=data.get("last_changed"),
                last_updated=data.get("last_updated"),
                context=data.get("context")
            )
        except Exception as e:
            logger.warning(f"Failed to parse entity state: {e}")
            return None
    
    def _should_track_entity(self, entity_id: str) -> bool:
        """Check if entity should be tracked based on domain filters."""
        if not settings.SUBSCRIBE_DOMAINS:
            return True
        domain = entity_id.split(".")[0]
        return domain in settings.SUBSCRIBE_DOMAINS
    
    async def _handle_message(self, msg: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(msg)
            msg_type = data.get("type")
            msg_id = data.get("id")
            
            # Handle pending request responses
            if msg_id and msg_id in self._pending:
                ha_msg = HAMessage(
                    type=msg_type,
                    id=msg_id,
                    success=data.get("success"),
                    result=data.get("result"),
                    message=data.get("message")
                )
                self._pending[msg_id].set_result(ha_msg)
                return
            
            # Handle events
            if msg_type == "event":
                event = data.get("event", {})
                event_type = event.get("event_type")
                
                if event_type == "state_changed":
                    event_data = event.get("data", {})
                    new_state = event_data.get("new_state")
                    
                    if new_state:
                        entity = self._parse_entity_state(new_state)
                        if entity and self._should_track_entity(entity.entity_id):
                            self.states[entity.entity_id] = entity
                            self.status.last_event = datetime.utcnow()
                            
                            if self._on_state_change:
                                try:
                                    self._on_state_change(entity)
                                except Exception as e:
                                    logger.error(f"State change callback error: {e}")
            
            elif msg_type == "result":
                # Unhandled result (no pending request)
                pass
            
            elif msg_type == "pong":
                # Heartbeat response
                pass
        
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _heartbeat(self) -> None:
        """Send periodic heartbeat pings."""
        while self._running and self._ws:
            try:
                await asyncio.sleep(30)
                if self._ws:
                    await self._send({
                        "id": self._next_id(),
                        "type": "ping"
                    })
            except Exception:
                break
    
    async def _connect(self) -> bool:
        """Establish WebSocket connection."""
        try:
            self._ws = await websockets.connect(
                settings.HA_WS_URL,
                ping_interval=None,  # We handle our own heartbeat
                close_timeout=5
            )
            return True
        except Exception as e:
            self.status.error = str(e)
            logger.error(f"Connection failed: {e}")
            return False
    
    async def start(self) -> None:
        """Start the WebSocket client with auto-reconnect."""
        self._running = True
        delay = self._reconnect_delay
        
        while self._running:
            try:
                logger.info(f"Connecting to {settings.HA_WS_URL}")
                
                if not await self._connect():
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._max_reconnect_delay)
                    continue
                
                if not await self._authenticate():
                    await self.disconnect()
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._max_reconnect_delay)
                    continue
                
                if not await self._subscribe_events():
                    await self.disconnect()
                    await asyncio.sleep(delay)
                    continue
                
                # Fetch initial states
                await self._fetch_states()
                
                # Fetch registries for area mapping
                await self._fetch_registries()
                
                # Reset delay on successful connection
                delay = self._reconnect_delay
                
                if self._on_connect:
                    self._on_connect()
                
                # Start heartbeat
                heartbeat_task = asyncio.create_task(self._heartbeat())
                
                # Main message loop
                try:
                    async for msg in self._ws:
                        await self._handle_message(msg)
                except ConnectionClosed as e:
                    logger.warning(f"Connection closed: {e}")
                finally:
                    heartbeat_task.cancel()
                
            except WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
            
            # Connection lost
            self.status.connected = False
            self.status.error = "Disconnected"
            
            if self._on_disconnect:
                self._on_disconnect(self.status.error)
            
            if self._running:
                logger.info(f"Reconnecting in {delay}s...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)
    
    async def disconnect(self) -> None:
        """Disconnect from Home Assistant."""
        self._running = False
        self.status.connected = False
        
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
    
    def get_entity(self, entity_id: str) -> Optional[EntityState]:
        """Get current state of an entity."""
        return self.states.get(entity_id)
    
    def get_entities_by_domain(self, domain: str) -> list[EntityState]:
        """Get all entities of a specific domain."""
        return [
            e for e in self.states.values()
            if e.entity_id.startswith(f"{domain}.")
        ]
    
    def get_all_entities(self) -> dict[str, EntityState]:
        """Get all entity states."""
        return self.states.copy()
    
    async def webrtc_offer(self, entity_id: str, offer_sdp: str) -> Optional[dict[str, Any]]:
        """
        Send WebRTC offer to Home Assistant and get answer.
        
        This is used for camera streaming via WebRTC.
        Note: Many cameras (like Eufy) don't support WebRTC and will return an error.
        
        Args:
            entity_id: Camera entity ID (e.g., camera.achterdeur)
            offer_sdp: SDP offer from the client
            
        Returns:
            Dict with 'answer' SDP or None on error
        """
        if not self._ws or not self.status.connected:
            logger.error("WebRTC offer failed: not connected to HA")
            return None
        
        try:
            msg = {
                "type": "camera/web_rtc_offer",
                "entity_id": entity_id,
                "offer": offer_sdp
            }
            response = await self._send_and_wait(msg, timeout=30.0)
            
            if response.success:
                return {"answer": response.result.get("answer")}
            else:
                error_msg = response.message or "WebRTC negotiation failed"
                logger.error(f"WebRTC offer failed: {error_msg}")
                return {"error": error_msg}
        except asyncio.TimeoutError:
            logger.error("WebRTC offer timed out")
            return {"error": "WebRTC negotiation timed out"}
        except Exception as e:
            logger.error(f"WebRTC offer error: {e}")
            return {"error": str(e)}
    
    async def get_camera_stream(self, entity_id: str) -> Optional[dict[str, Any]]:
        """
        Request HLS stream URL for a camera.
        
        Args:
            entity_id: Camera entity ID
            
        Returns:
            Dict with 'url' for HLS stream or None on error
        """
        if not self._ws or not self.status.connected:
            logger.error("Stream request failed: not connected to HA")
            return None
        
        try:
            msg = {
                "type": "camera/stream",
                "entity_id": entity_id,
            }
            response = await self._send_and_wait(msg, timeout=30.0)
            
            if response.success and response.result:
                return {"url": response.result.get("url")}
            else:
                error_msg = response.message or "Failed to start stream"
                logger.error(f"Camera stream failed: {error_msg}")
                return {"error": error_msg}
        except asyncio.TimeoutError:
            logger.error("Camera stream request timed out")
            return {"error": "Stream request timed out"}
        except Exception as e:
            logger.error(f"Camera stream error: {e}")
            return {"error": str(e)}


# Singleton instance
ha_client = HAWebSocketClient()
