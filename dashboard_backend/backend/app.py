"""
FastAPI application for Home Assistant Dashboard.

Provides REST API endpoints and serves the PWA frontend.
Runs on http://127.0.0.1:8000 for local access.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import aiohttp
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .compute import compute_engine
from .diagnostics import diagnostics
from .ha_rest import ha_rest
from .ha_ws import ha_client
from .models import DashboardState, EntityState, ServiceCall, ServiceResponse
from .settings import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# WebSocket clients for real-time updates
ws_clients: set[WebSocket] = set()


async def broadcast_state_update(entity: EntityState) -> None:
    """Broadcast entity state update to all connected WebSocket clients."""
    if not ws_clients:
        return
    
    message = {
        "type": "state_changed",
        "entity_id": entity.entity_id,
        "state": entity.state,
        "attributes": entity.attributes,
        "last_updated": entity.last_updated.isoformat() if entity.last_updated else None
    }
    
    disconnected = set()
    for client in ws_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.add(client)
    
    ws_clients.difference_update(disconnected)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Home Assistant Dashboard Backend")
    
    # Validate settings
    valid, error = settings.validate()
    if not valid:
        logger.error(f"Invalid settings: {error}")
        logger.warning("Starting without HA connection - configure .env file")
    else:
        # Register WebSocket callbacks
        ha_client.on_state_change(lambda e: asyncio.create_task(broadcast_state_update(e)))
        ha_client.on_connect(lambda: logger.info("Connected to Home Assistant"))
        ha_client.on_disconnect(lambda e: logger.warning(f"Disconnected: {e}"))
        
        # Start WebSocket client in background
        asyncio.create_task(ha_client.start())
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await ha_client.disconnect()
    await ha_rest.close()


# Create FastAPI app
app = FastAPI(
    title="Home Assistant Dashboard",
    description="Local microservice for Home Assistant dashboard",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware (allow local browser access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for PWA
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


# =============================================================================
# Health & Diagnostics
# =============================================================================

@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Simple health check endpoint."""
    healthy, message = await diagnostics.health_check()
    return {
        "status": "healthy" if healthy else "unhealthy",
        "message": message
    }


@app.get("/diagnostics")
async def get_diagnostics() -> dict[str, Any]:
    """Get full diagnostics report."""
    return await diagnostics.get_full_diagnostics()


# =============================================================================
# Entity State Endpoints
# =============================================================================

@app.get("/api/states")
async def get_all_states() -> dict[str, Any]:
    """Get all entity states from cache."""
    entities = ha_client.get_all_entities()
    return {
        "entities": {k: v.model_dump() for k, v in entities.items()},
        "count": len(entities),
        "connected": ha_client.status.connected
    }


@app.get("/api/states/{entity_id}")
async def get_entity_state(entity_id: str) -> EntityState:
    """Get state of a specific entity."""
    entity = ha_client.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
    return entity


@app.get("/api/states/domain/{domain}")
async def get_states_by_domain(domain: str) -> list[EntityState]:
    """Get all entities of a specific domain."""
    return ha_client.get_entities_by_domain(domain)


# =============================================================================
# Dashboard State (Aggregated)
# =============================================================================

@app.get("/api/dashboard")
async def get_dashboard_state() -> DashboardState:
    """Get complete dashboard state with computed values."""
    entities = ha_client.get_all_entities()
    return compute_engine.build_dashboard_state(
        entities=entities,
        connected=ha_client.status.connected,
        areas_registry=ha_client.areas,
        entities_registry=ha_client.entities_registry
    )


@app.get("/api/comfort")
async def get_comfort_score() -> dict[str, Any]:
    """Get current comfort score."""
    entities = ha_client.get_all_entities()
    comfort = compute_engine.compute_comfort_score(entities)
    return comfort.model_dump()


@app.get("/api/energy")
async def get_energy_summary() -> dict[str, Any]:
    """Get energy consumption summary."""
    entities = ha_client.get_all_entities()
    energy = compute_engine.compute_energy_summary(entities)
    return energy.model_dump()


@app.get("/api/rooms")
async def get_rooms() -> list[dict[str, Any]]:
    """Get entities grouped by room/area."""
    entities = ha_client.get_all_entities()
    rooms = compute_engine.aggregate_by_area(
        entities,
        ha_client.areas,
        ha_client.entities_registry
    )
    return [r.model_dump() for r in rooms]


@app.get("/api/areas")
async def get_areas() -> dict[str, Any]:
    """Get all areas from HA registry."""
    return {
        "areas": ha_client.areas,
        "count": len(ha_client.areas)
    }


@app.get("/api/cameras")
async def get_cameras() -> list[dict[str, Any]]:
    """Get all camera entities."""
    entities = ha_client.get_all_entities()
    return compute_engine.get_cameras(entities)


@app.get("/api/summary")
async def get_entity_summary() -> dict[str, Any]:
    """Get summary counts by domain."""
    entities = ha_client.get_all_entities()
    return compute_engine.get_entity_summary(entities)


# =============================================================================
# Service Calls (Commands)
# =============================================================================

@app.post("/api/services/call")
async def call_service(call: ServiceCall) -> ServiceResponse:
    """Call a Home Assistant service."""
    return await ha_rest.call_service(call)


@app.post("/api/services/{domain}/{service}")
async def call_service_simple(
    domain: str,
    service: str,
    entity_id: Optional[str] = None,
    data: Optional[dict[str, Any]] = None
) -> ServiceResponse:
    """Call a Home Assistant service (simplified)."""
    call = ServiceCall(
        domain=domain,
        service=service,
        entity_id=entity_id,
        data=data or {}
    )
    return await ha_rest.call_service(call)


@app.post("/api/entity/{entity_id}/turn_on")
async def turn_on_entity(entity_id: str, data: Optional[dict[str, Any]] = None) -> ServiceResponse:
    """Turn on an entity."""
    return await ha_rest.turn_on(entity_id, **(data or {}))


@app.post("/api/entity/{entity_id}/turn_off")
async def turn_off_entity(entity_id: str) -> ServiceResponse:
    """Turn off an entity."""
    return await ha_rest.turn_off(entity_id)


@app.post("/api/entity/{entity_id}/toggle")
async def toggle_entity(entity_id: str) -> ServiceResponse:
    """Toggle an entity."""
    return await ha_rest.toggle(entity_id)


# =============================================================================
# Climate Controls
# =============================================================================

@app.post("/api/climate/{entity_id}/set_temperature")
async def set_climate_temperature(entity_id: str, temperature: float) -> ServiceResponse:
    """Set target temperature for a climate entity."""
    return await ha_rest.set_temperature(entity_id, temperature)


@app.post("/api/climate/{entity_id}/set_hvac_mode")
async def set_climate_hvac_mode(entity_id: str, hvac_mode: str) -> ServiceResponse:
    """Set HVAC mode for a climate entity."""
    return await ha_rest.set_hvac_mode(entity_id, hvac_mode)


# =============================================================================
# Camera Proxy
# =============================================================================

@app.get("/api/camera_proxy/{entity_id}")
async def proxy_camera_image(entity_id: str):
    """Proxy camera image from Home Assistant with authentication."""
    # Build full entity ID
    full_entity_id = f"camera.{entity_id}" if not entity_id.startswith("camera.") else entity_id
    
    # Use Home Assistant's camera_proxy endpoint directly - it always returns a snapshot
    image_url = f"{settings.HA_URL}/api/camera_proxy/{full_entity_id}"
    
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {settings.HA_TOKEN}"}
        try:
            async with session.get(image_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    return StreamingResponse(
                        iter([content]),
                        media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
                    )
                else:
                    logger.error(f"Camera proxy failed for {full_entity_id}: {resp.status}")
        except Exception as e:
            logger.error(f"Camera proxy error for {full_entity_id}: {e}")
    
    # Return a placeholder SVG image when camera is unavailable
    placeholder = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
        <rect fill="#1a1a2e" width="320" height="180"/>
        <text x="160" y="85" text-anchor="middle" fill="#666" font-size="14" font-family="sans-serif">Camera Unavailable</text>
        <text x="160" y="105" text-anchor="middle" fill="#444" font-size="10" font-family="sans-serif">Tap to wake</text>
    </svg>'''
    return StreamingResponse(
        iter([placeholder.encode()]),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/api/image_proxy/{entity_id}")
async def proxy_image_entity(entity_id: str):
    """Proxy image entity from Home Assistant (e.g., event images from Eufy)."""
    # Build full entity ID
    full_entity_id = f"image.{entity_id}" if not entity_id.startswith("image.") else entity_id
    
    # Get the entity to find the entity_picture URL
    entity = ha_client.get_entity(full_entity_id)
    if entity and entity.attributes.get("entity_picture"):
        image_url = f"{settings.HA_URL}{entity.attributes['entity_picture']}"
    else:
        # Fallback to image_proxy endpoint
        image_url = f"{settings.HA_URL}/api/image_proxy/{full_entity_id}"
    
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {settings.HA_TOKEN}"}
        try:
            async with session.get(image_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")
                    return StreamingResponse(
                        iter([content]),
                        media_type=content_type,
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
                    )
                else:
                    logger.error(f"Image proxy failed for {full_entity_id}: {resp.status}")
        except Exception as e:
            logger.error(f"Image proxy error for {full_entity_id}: {e}")
    
    # Return a placeholder SVG image when unavailable
    placeholder = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
        <rect fill="#1a1a2e" width="320" height="180"/>
        <text x="160" y="90" text-anchor="middle" fill="#666" font-size="14" font-family="sans-serif">No Event Image</text>
    </svg>'''
    return StreamingResponse(
        iter([placeholder.encode()]),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.post("/api/camera/{entity_id}/start_stream")
async def start_camera_stream(entity_id: str) -> dict[str, Any]:
    """
    Start P2P livestream for Eufy cameras.
    
    This wakes up the camera and starts streaming, which provides
    better quality snapshots during live refresh mode.
    """
    full_id = f"camera.{entity_id}" if not entity_id.startswith("camera.") else entity_id
    entity = ha_client.get_entity(full_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Try to start P2P livestream (works for Eufy cameras)
    try:
        result = await ha_rest.call_service(ServiceCall(
            domain="eufy_security",
            service="start_p2p_livestream",
            entity_id=full_id,
            data={}
        ))
        logger.info(f"Started P2P stream for {full_id}")
        return {"success": True, "message": "Stream started", "entity_id": full_id}
    except Exception as e:
        logger.warning(f"Failed to start P2P stream for {full_id}: {e}")
        # Non-fatal - camera may not be Eufy or service unavailable
        return {"success": False, "message": str(e), "entity_id": full_id}


@app.post("/api/camera/{entity_id}/stop_stream")
async def stop_camera_stream(entity_id: str) -> dict[str, Any]:
    """
    Stop P2P livestream for Eufy cameras.
    
    Called when closing the camera fullscreen view to save bandwidth/battery.
    """
    full_id = f"camera.{entity_id}" if not entity_id.startswith("camera.") else entity_id
    entity = ha_client.get_entity(full_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Try to stop P2P livestream
    try:
        result = await ha_rest.call_service(ServiceCall(
            domain="eufy_security",
            service="stop_p2p_livestream",
            entity_id=full_id,
            data={}
        ))
        logger.info(f"Stopped P2P stream for {full_id}")
        return {"success": True, "message": "Stream stopped", "entity_id": full_id}
    except Exception as e:
        logger.warning(f"Failed to stop P2P stream for {full_id}: {e}")
        return {"success": False, "message": str(e), "entity_id": full_id}


@app.get("/api/camera_stream/{entity_id}")
async def proxy_camera_stream(entity_id: str):
    """
    Proxy MJPEG camera stream from Home Assistant.
    
    This provides a continuous video stream via multipart MJPEG.
    Can be used directly in an <img> tag for live video.
    """
    full_id = f"camera.{entity_id}" if not entity_id.startswith("camera.") else entity_id
    entity = ha_client.get_entity(full_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # HA's MJPEG stream endpoint
    stream_url = f"{settings.HA_URL}/api/camera_proxy_stream/{full_id}"
    
    async def stream_mjpeg():
        timeout = aiohttp.ClientTimeout(total=None, connect=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {"Authorization": f"Bearer {settings.HA_TOKEN}"}
            try:
                async with session.get(stream_url, headers=headers) as resp:
                    if resp.status != 200:
                        logger.error(f"Camera stream failed: {resp.status}")
                        return
                    
                    # Stream the MJPEG data
                    async for chunk in resp.content.iter_any():
                        yield chunk
            except asyncio.CancelledError:
                logger.info(f"Camera stream cancelled: {entity_id}")
            except Exception as e:
                logger.error(f"Camera stream error: {e}")
    
    return StreamingResponse(
        stream_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
        }
    )


@app.post("/api/camera_webrtc/{entity_id}")
async def webrtc_offer(entity_id: str, request_data: dict):
    """
    Handle WebRTC signaling for camera streams.
    
    Accepts an SDP offer from the client and returns an SDP answer
    from Home Assistant for establishing a WebRTC connection.
    
    Request body: {"offer": "<SDP offer string>"}
    Response: {"answer": "<SDP answer string>"} or {"error": "message"}
    """
    full_id = f"camera.{entity_id}" if not entity_id.startswith("camera.") else entity_id
    entity = ha_client.get_entity(full_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    offer_sdp = request_data.get("offer")
    if not offer_sdp:
        raise HTTPException(status_code=400, detail="Missing 'offer' in request body")
    
    result = await ha_client.webrtc_offer(full_id, offer_sdp)
    
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to connect to Home Assistant")
    
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    
    return JSONResponse(result)


@app.get("/api/camera_hls/{entity_id}")
async def get_camera_hls_stream(entity_id: str):
    """
    Get HLS stream URL for a camera.
    
    Returns the HLS playlist URL that can be played with hls.js or native video player.
    """
    full_id = f"camera.{entity_id}" if not entity_id.startswith("camera.") else entity_id
    entity = ha_client.get_entity(full_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    result = await ha_client.get_camera_stream(full_id)
    
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to connect to Home Assistant")
    
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    
    return JSONResponse(result)


@app.get("/api/image_proxy/{entity_id}")
async def proxy_image_entity(entity_id: str):
    """Proxy image entity from Home Assistant with authentication."""
    full_id = f"image.{entity_id}" if not entity_id.startswith("image.") else entity_id
    entity = ha_client.get_entity(full_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Image entity not found")
    
    entity_picture = entity.attributes.get("entity_picture", "")
    if not entity_picture:
        raise HTTPException(status_code=404, detail="No image available")
    
    image_url = f"{settings.HA_URL}{entity_picture}"
    
    async def stream_image():
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {settings.HA_TOKEN}"}
            async with session.get(image_url, headers=headers) as resp:
                if resp.status != 200:
                    return
                async for chunk in resp.content.iter_chunked(8192):
                    yield chunk
    
    return StreamingResponse(
        stream_image(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


# =============================================================================
# WebSocket for Real-time Updates
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time state updates."""
    await websocket.accept()
    ws_clients.add(websocket)
    logger.info(f"WebSocket client connected ({len(ws_clients)} total)")
    
    try:
        # Send initial state
        entities = ha_client.get_all_entities()
        dashboard = compute_engine.build_dashboard_state(
            entities=entities,
            connected=ha_client.status.connected,
            areas_registry=ha_client.areas,
            entities_registry=ha_client.entities_registry
        )
        cameras = compute_engine.get_cameras(entities)
        
        await websocket.send_json({
            "type": "initial_state",
            "data": dashboard.model_dump(mode="json"),
            "cameras": cameras,
            "areas": ha_client.areas
        })
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                data = await websocket.receive_json()
                
                # Handle ping/pong
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                
                # Handle service calls from WebSocket
                elif data.get("type") == "service_call":
                    call = ServiceCall(**data.get("data", {}))
                    result = await ha_rest.call_service(call)
                    await websocket.send_json({
                        "type": "service_result",
                        "data": result.model_dump()
                    })
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                break
    
    finally:
        ws_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected ({len(ws_clients)} remaining)")


# =============================================================================
# PWA Frontend Serving
# =============================================================================

@app.get("/manifest.json")
async def get_manifest():
    """Serve PWA manifest."""
    manifest_path = frontend_path / "manifest.json"
    if manifest_path.exists():
        return FileResponse(manifest_path, media_type="application/json")
    raise HTTPException(status_code=404, detail="Manifest not found")


@app.get("/service-worker.js")
async def get_service_worker():
    """Serve service worker."""
    sw_path = frontend_path / "service-worker.js"
    if sw_path.exists():
        return FileResponse(sw_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Service worker not found")


@app.get("/")
@app.get("/{path:path}")
async def serve_frontend(path: str = ""):
    """Serve the PWA frontend."""
    # Check for specific static files first
    if path and not path.startswith("api/"):
        file_path = frontend_path / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
    
    # Default to index.html (SPA routing)
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    
    # Fallback response if frontend not found
    return JSONResponse({
        "message": "Home Assistant Dashboard API",
        "docs": "/docs",
        "health": "/health"
    })
