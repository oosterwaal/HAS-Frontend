/**
 * Home Assistant Dashboard PWA - LCARS Interface
 * Connects to local FastAPI backend at http://127.0.0.1:8000
 */

const API_BASE = 'http://127.0.0.1:8000';
const WS_URL = 'ws://127.0.0.1:8000/ws';

// Application State
const state = {
    connected: false,
    entities: {},
    comfort: null,
    energy: null,
    rooms: [],
    cameras: [],
    areas: {},
    filter: {
        domain: '',
        search: ''
    },
    currentSection: 'comfort',
    expandedRooms: new Set()
};

// WebSocket connection
let ws = null;
let wsReconnectTimeout = null;

// DOM Elements
const elements = {
    connectionStatusText: document.getElementById('connection-status-text'),
    connectionPanel: document.getElementById('connection-panel'),
    entityCountDisplay: document.getElementById('entity-count-display'),
    comfortDisplay: document.getElementById('comfort-display'),
    tempDisplay: document.getElementById('temp-display'),
    humidityDisplay: document.getElementById('humidity-display'),
    energyDisplay: document.getElementById('energy-display'),
    comfortScore: document.getElementById('comfort-score'),
    temperature: document.getElementById('temperature'),
    humidity: document.getElementById('humidity'),
    energyTotal: document.getElementById('energy-total'),
    camerasGrid: document.getElementById('cameras-grid'),
    quickControlsGrid: document.getElementById('quick-controls-grid'),
    roomSectionsContainer: document.getElementById('room-sections-container'),
    mainNav: document.getElementById('main-nav'),
    toastContainer: document.getElementById('toast-container')
};

// =============================================================================
// LCARS Navigation & Sound
// =============================================================================

function showSection(sectionName) {
    state.currentSection = sectionName;
    
    // Hide all sections
    document.querySelectorAll('.lcars-section').forEach(section => {
        section.classList.remove('active');
    });
    
    // Update nav button states
    document.querySelectorAll('#main-nav .nav-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.section === sectionName) {
            btn.classList.add('active');
        }
    });
    
    // Show selected section
    const targetSection = document.getElementById(`section-${sectionName}`);
    if (targetSection) {
        targetSection.classList.add('active');
    }
    
    // Update banner with current page name
    const banner = document.querySelector('.banner');
    if (banner) {
        const pageName = sectionName.replace('room-', '').toUpperCase();
        const stardateEl = document.getElementById('stardate');
        const stardateText = stardateEl ? stardateEl.textContent : '';
        banner.innerHTML = `GEEKBASE/${pageName} • <span id="stardate">${stardateText}</span>`;
    }
}

function playSound(audioId) {
    const audio = document.getElementById(audioId);
    if (audio) {
        audio.currentTime = 0;
        audio.play().catch(() => {}); // Ignore autoplay restrictions
    }
}

// Display current date/time as DDMMYY:HH:MM:SS
function updateStardate() {
    const now = new Date();
    const dd = String(now.getDate()).padStart(2, '0');
    const mm = String(now.getMonth() + 1).padStart(2, '0');
    const yy = String(now.getFullYear()).slice(-2);
    const hh = String(now.getHours()).padStart(2, '0');
    const min = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    
    const stardate = `${dd}${mm}${yy}:${hh}:${min}:${ss}`;
    
    const stardateEl = document.getElementById('stardate');
    if (stardateEl) {
        stardateEl.textContent = stardate;
    }
}

// =============================================================================
// WebSocket Connection
// =============================================================================

function connectWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    
    console.log('Connecting to WebSocket...');
    ws = new WebSocket(WS_URL);
    
    ws.onopen = () => {
        console.log('WebSocket connected');
        updateConnectionStatus(true);
        clearTimeout(wsReconnectTimeout);
    };
    
    ws.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
        }
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);
        scheduleReconnect();
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        updateConnectionStatus(false);
    };
}

function scheduleReconnect() {
    clearTimeout(wsReconnectTimeout);
    wsReconnectTimeout = setTimeout(() => {
        console.log('Attempting to reconnect...');
        connectWebSocket();
    }, 5000);
}

function handleWebSocketMessage(message) {
    switch (message.type) {
        case 'initial_state':
            handleInitialState(message.data, message.cameras, message.areas);
            break;
        case 'state_changed':
            handleStateChange(message);
            break;
        case 'service_result':
            handleServiceResult(message.data);
            break;
        case 'pong':
            // Heartbeat response
            break;
        default:
            console.log('Unknown message type:', message.type);
    }
}

function handleInitialState(data, cameras, areas) {
    state.entities = data.entities || {};
    state.comfort = data.comfort;
    state.energy = data.energy;
    state.rooms = data.rooms || [];
    state.cameras = cameras || [];
    state.areas = areas || {};
    state.connected = data.connected;
    
    updateUI();
}

function handleStateChange(message) {
    const entityId = message.entity_id;
    
    if (state.entities[entityId]) {
        state.entities[entityId] = {
            ...state.entities[entityId],
            state: message.state,
            attributes: message.attributes,
            last_updated: message.last_updated
        };
    } else {
        state.entities[entityId] = {
            entity_id: entityId,
            state: message.state,
            attributes: message.attributes,
            last_updated: message.last_updated
        };
    }
    
    // Update specific UI elements
    updateEntityInList(entityId);
    updateQuickControls();
    
    // Refresh computed values periodically
    debounce('refresh', () => fetchDashboardState(), 2000);
}

function handleServiceResult(data) {
    if (data.success) {
        showToast('Command sent', 'success');
    } else {
        showToast(data.message || 'Command failed', 'error');
    }
}

// =============================================================================
// API Calls
// =============================================================================

async function fetchDashboardState() {
    try {
        const response = await fetch(`${API_BASE}/api/dashboard`);
        if (response.ok) {
            const data = await response.json();
            state.entities = data.entities || {};
            state.comfort = data.comfort;
            state.energy = data.energy;
            state.rooms = data.rooms || [];
            state.connected = data.connected;
            updateUI();
        }
    } catch (error) {
        console.error('Failed to fetch dashboard state:', error);
    }
}

async function callService(domain, service, entityId, data = {}) {
    try {
        const response = await fetch(`${API_BASE}/api/services/call`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                domain,
                service,
                entity_id: entityId,
                data
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast('Command sent', 'success');
        } else {
            showToast(result.message || 'Command failed', 'error');
        }
        
        return result;
    } catch (error) {
        console.error('Service call failed:', error);
        showToast('Connection error', 'error');
        return { success: false, message: error.message };
    }
}

async function toggleEntity(entityId) {
    const entity = state.entities[entityId];
    if (!entity) return;
    
    const domain = entityId.split('.')[0];
    const isOn = entity.state === 'on';
    const service = isOn ? 'turn_off' : 'turn_on';
    
    await callService(domain, service, entityId);
}

// =============================================================================
// UI Updates
// =============================================================================

function updateConnectionStatus(connected) {
    state.connected = connected;
    
    // Update LCARS data cascade display
    if (elements.connectionStatusText) {
        elements.connectionStatusText.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
        elements.connectionStatusText.style.color = connected ? 'var(--accent-success)' : 'var(--tomato)';
    }
    
    // Update left panel indicator
    if (elements.connectionPanel) {
        elements.connectionPanel.style.backgroundColor = connected ? 'var(--accent-success)' : 'var(--tomato)';
    }
}

function updateUI() {
    updateComfort();
    updateEnergy();
    updateCameras();
    updateDoorbellCamera();
    buildNavigation();
    buildRoomSections();
    updateQuickControls();
    updateRoomSections();
    updateLCARSDisplay();
}

function updateLCARSDisplay() {
    // Update LCARS data cascade values
    const entityCount = Object.keys(state.entities).length;
    
    if (elements.entityCountDisplay) {
        elements.entityCountDisplay.textContent = `ENTITIES: ${entityCount}`;
    }
    
    if (state.comfort) {
        if (elements.comfortDisplay) {
            elements.comfortDisplay.textContent = `COMFORT: ${Math.round(state.comfort.score)}`;
        }
        if (elements.tempDisplay) {
            elements.tempDisplay.textContent = `TEMP: ${state.comfort.temperature || '--'}°C`;
        }
        if (elements.humidityDisplay) {
            elements.humidityDisplay.textContent = `HUMIDITY: ${state.comfort.humidity || '--'}%`;
        }
    }
    
    if (state.energy && elements.energyDisplay) {
        elements.energyDisplay.textContent = `ENERGY: ${state.energy.total_kwh.toFixed(1)} kWh`;
    }
}

function updateComfort() {
    if (state.comfort) {
        if (elements.comfortScore) {
            elements.comfortScore.textContent = Math.round(state.comfort.score);
        }
        if (elements.temperature) {
            elements.temperature.textContent = state.comfort.temperature 
                ? `${state.comfort.temperature}°C` 
                : '--°C';
        }
        if (elements.humidity) {
            elements.humidity.textContent = state.comfort.humidity 
                ? `${state.comfort.humidity}%` 
                : '--%';
        }
    }
}

function updateEnergy() {
    if (state.energy && elements.energyTotal) {
        elements.energyTotal.textContent = `${state.energy.total_kwh.toFixed(2)} kWh`;
    }
}

function updateCameras() {
    if (!elements.camerasGrid) return;
    
    if (!state.cameras || state.cameras.length === 0) {
        elements.camerasGrid.innerHTML = '<div class="empty-state">No cameras found</div>';
        return;
    }
    
    elements.camerasGrid.innerHTML = state.cameras.map(camera => {
        const entityId = camera.entity_id.replace('camera.', '');
        const imageUrl = getEventImageUrl(camera.entity_id);
        const statusClass = camera.state === 'unavailable' ? 'unavailable' : 
                           camera.is_streaming ? 'streaming' : 'idle';
        
        return `
            <div class="camera-item">
                <div class="camera-image-wrapper" onclick="openCameraFullscreen('${camera.entity_id}')">
                    <img class="camera-image loading" 
                         id="cam-${entityId}"
                         data-src="${imageUrl}"
                         data-entity="${camera.entity_id}"
                         alt="${camera.name}"
                         onload="this.classList.remove('loading')"
                         onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 9%22><rect fill=%22%231a1a2e%22 width=%2216%22 height=%229%22/><text x=%228%22 y=%225%22 text-anchor=%22middle%22 fill=%22%23666%22 font-size=%221%22>No Image</text></svg>'; this.classList.remove('loading')">
                    <span class="camera-live-badge">● View</span>
                </div>
                <div class="camera-info">
                    <div class="camera-name-row">
                        <span class="camera-name">${camera.name}</span>
                        <span class="camera-status ${statusClass}">${camera.state}</span>
                    </div>
                    <div class="camera-meta">
                        <span class="camera-updated">Tap to view camera</span>
                        <button class="camera-refresh-btn" onclick="event.stopPropagation(); refreshSingleCamera('${camera.entity_id}')" title="Refresh thumbnail">🔄</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    // Lazy load images
    setTimeout(() => {
        document.querySelectorAll('.camera-image[data-src]').forEach(img => {
            img.src = img.dataset.src;
        });
    }, 100);
}

// =============================================================================
// Camera Event Image Mapping
// =============================================================================

// Map camera entities to their event image entities
const CAMERA_EVENT_IMAGE_MAP = {
    'camera.deurbel': 'deurbel_event_image',
    'camera.schuur': 'schuur_event_image',
    'camera.achterdeur': 'achterdeur_event_image'
};

function getEventImageUrl(cameraEntityId) {
    const eventImageId = CAMERA_EVENT_IMAGE_MAP[cameraEntityId];
    if (eventImageId) {
        return `${API_BASE}/api/image_proxy/${eventImageId}?t=${Date.now()}`;
    }
    // Fallback to camera proxy for cameras without event images
    const shortId = cameraEntityId.replace('camera.', '');
    return `${API_BASE}/api/camera_proxy/${shortId}?t=${Date.now()}`;
}

// =============================================================================
// Doorbell Camera (Comfort Page)
// =============================================================================

function updateDoorbellCamera() {
    const doorbellImg = document.getElementById('doorbell-image');
    if (!doorbellImg) return;
    
    // Use event image from image.deurbel_event_image
    doorbellImg.src = `${API_BASE}/api/image_proxy/deurbel_event_image?t=${Date.now()}`;
    doorbellImg.dataset.entityId = 'camera.deurbel';
}

function openDoorbellFullscreen() {
    const doorbellImg = document.getElementById('doorbell-image');
    const entityId = doorbellImg?.dataset?.entityId;
    if (entityId) {
        openCameraFullscreen(entityId);
    }
}

function formatTime(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// =============================================================================
// Camera Streaming
// =============================================================================

let cameraRefreshInterval = null;
let cameraRefreshRate = 2000; // ms
let currentStreamingCamera = null;

async function startCameraP2PStream(entityId) {
    const shortId = entityId.replace('camera.', '');
    try {
        const response = await fetch(`${API_BASE}/api/camera/${shortId}/start_stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const result = await response.json();
        if (result.success) {
            console.log(`P2P stream started for ${entityId}`);
            currentStreamingCamera = entityId;
        } else {
            console.log(`P2P stream not available for ${entityId}: ${result.message}`);
        }
    } catch (e) {
        console.log(`Failed to start P2P stream: ${e}`);
    }
}

async function stopCameraP2PStream(entityId) {
    if (!entityId) return;
    const shortId = entityId.replace('camera.', '');
    try {
        const response = await fetch(`${API_BASE}/api/camera/${shortId}/stop_stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const result = await response.json();
        if (result.success) {
            console.log(`P2P stream stopped for ${entityId}`);
        }
    } catch (e) {
        console.log(`Failed to stop P2P stream: ${e}`);
    }
    currentStreamingCamera = null;
}

async function openCameraFullscreen(entityId) {
    const camera = state.cameras.find(c => c.entity_id === entityId);
    if (!camera) return;
    
    const shortId = entityId.replace('camera.', '');
    const snapshotUrl = getEventImageUrl(entityId);
    
    const overlay = document.createElement('div');
    overlay.className = 'camera-fullscreen';
    overlay.id = 'camera-fullscreen-overlay';
    overlay.innerHTML = `
        <button class="close-btn" onclick="closeCameraFullscreen()">✕ Close</button>
        <div class="fullscreen-stream-container">
            <img id="fullscreen-cam-img" class="fullscreen-stream" src="${snapshotUrl}" alt="${camera.name}">
            <div class="stream-live-indicator" id="stream-indicator">● Auto</div>
        </div>
        <div class="fullscreen-camera-info">
            <div class="fullscreen-camera-name">${camera.name}</div>
            <div class="fullscreen-camera-controls">
                <button class="stream-mode-btn active" id="btn-live" onclick="toggleLiveMode('${shortId}')">⏸ Pause</button>
                <button class="stream-mode-btn" onclick="manualRefresh('${shortId}')">🔄 Refresh</button>
                <select class="refresh-rate-select" onchange="setRefreshRate(this.value, '${shortId}')">
                    <option value="1000">1s</option>
                    <option value="2000" selected>2s</option>
                    <option value="3000">3s</option>
                    <option value="5000">5s</option>
                </select>
            </div>
            <div class="stream-status" id="stream-status">Auto refresh every 2s</div>
        </div>
    `;
    overlay.onclick = (e) => {
        if (e.target === overlay) closeCameraFullscreen();
    };
    
    document.body.appendChild(overlay);
    
    // Start P2P stream for better quality (Eufy cameras)
    // Then start refresh after a brief delay to let camera wake up
    startCameraP2PStream(entityId).then(() => {
        setTimeout(() => startLiveRefresh(shortId), 1000);
    });
}

function startLiveRefresh(shortId) {
    const img = document.getElementById('fullscreen-cam-img');
    const indicator = document.getElementById('stream-indicator');
    const status = document.getElementById('stream-status');
    
    if (!img) return;
    
    // Stop any existing interval
    if (cameraRefreshInterval) {
        clearInterval(cameraRefreshInterval);
    }
    
    // Add error handler to prevent image from disappearing on failed loads
    img.onerror = () => {
        console.log('Camera image load failed, keeping previous frame');
        // Don't change the image - keep showing the last successful frame
    };
    
    // Initial load - use event image
    const fullEntityId = `camera.${shortId}`;
    img.src = getEventImageUrl(fullEntityId);
    indicator.textContent = '● Auto';
    indicator.classList.add('connected');
    indicator.style.display = 'flex';
    
    const rateSeconds = cameraRefreshRate / 1000;
    status.textContent = `Auto refresh every ${rateSeconds}s`;
    
    // Update pause button
    const pauseBtn = document.getElementById('btn-live');
    if (pauseBtn) {
        pauseBtn.textContent = '⏸ Pause';
        pauseBtn.classList.add('active');
    }
    
    // Refresh at configured rate
    cameraRefreshInterval = setInterval(() => {
        if (document.getElementById('camera-fullscreen-overlay')) {
            img.src = getEventImageUrl(fullEntityId);
        } else {
            clearInterval(cameraRefreshInterval);
            cameraRefreshInterval = null;
        }
    }, cameraRefreshRate);
}

function toggleLiveMode(shortId) {
    const pauseBtn = document.getElementById('btn-live');
    const indicator = document.getElementById('stream-indicator');
    const status = document.getElementById('stream-status');
    
    if (cameraRefreshInterval) {
        // Currently running - pause it
        clearInterval(cameraRefreshInterval);
        cameraRefreshInterval = null;
        pauseBtn.textContent = '▶ Resume';
        pauseBtn.classList.remove('active');
        indicator.textContent = '⏸ Paused';
        indicator.classList.remove('connected');
        status.textContent = 'Paused - tap Resume to continue';
    } else {
        // Currently paused - resume it
        startLiveRefresh(shortId);
    }
}

function setRefreshRate(rate, shortId) {
    cameraRefreshRate = parseInt(rate);
    const status = document.getElementById('stream-status');
    const rateSeconds = cameraRefreshRate / 1000;
    status.textContent = `Auto refresh every ${rateSeconds}s`;
    
    // Restart with new rate if currently running
    if (cameraRefreshInterval) {
        startLiveRefresh(shortId);
    }
}

function manualRefresh(shortId) {
    const img = document.getElementById('fullscreen-cam-img');
    if (img) {
        const fullEntityId = `camera.${shortId}`;
        img.src = getEventImageUrl(fullEntityId);
        showToast('Refreshed', 'info');
    }
}

function closeCameraFullscreen() {
    // Clean up refresh interval
    if (cameraRefreshInterval) {
        clearInterval(cameraRefreshInterval);
        cameraRefreshInterval = null;
    }
    
    // Stop P2P stream to save bandwidth/battery (Eufy cameras)
    if (currentStreamingCamera) {
        stopCameraP2PStream(currentStreamingCamera);
    }
    
    const overlay = document.getElementById('camera-fullscreen-overlay');
    if (overlay) {
        overlay.remove();
    }
}

async function refreshSingleCamera(entityId) {
    const shortId = entityId.replace('camera.', '');
    const img = document.getElementById(`cam-${shortId}`);
    
    if (img) {
        img.classList.add('loading');
        // Force browser to refetch by adding new timestamp
        const baseUrl = img.dataset.src.split('?')[0];
        img.src = `${baseUrl}?t=${Date.now()}`;
    }
    
    showToast('Refreshing camera...', 'info');
}

function refreshCameras() {
    // Refresh camera images periodically
    document.querySelectorAll('.camera-image').forEach(img => {
        if (img.dataset.src) {
            const baseUrl = img.dataset.src.split('?')[0];
            img.src = `${baseUrl}?t=${Date.now()}`;
        }
    });
    
    // Also refresh doorbell camera on comfort page
    const doorbellImg = document.getElementById('doorbell-image');
    if (doorbellImg && doorbellImg.src) {
        const baseUrl = doorbellImg.src.split('?')[0];
        doorbellImg.src = `${baseUrl}?t=${Date.now()}`;
    }
}

// Build navigation with dynamic room buttons
function buildNavigation() {
    if (!elements.mainNav) return;
    if (!state.rooms || state.rooms.length === 0) return;
    
    // Remove existing room nav buttons (keep static ones)
    const existingRoomBtns = elements.mainNav.querySelectorAll('.nav-btn.room-nav');
    existingRoomBtns.forEach(btn => btn.remove());
    
    // Add room buttons after the static buttons (Comfort, Security)
    const controllableDomains = ['light', 'switch', 'fan'];
    // Skip these rooms in navigation (not needed as separate pages)
    const skipRooms = ['voordeur', 'unassigned'];
    // Custom room order (rooms not in list appear at the end)
    const roomOrder = ['jf kamer', 'breanna kamer', 'living room', 'bedroom', 'kantoor', 'tuin'];
    
    // Sort rooms by custom order
    const sortedRooms = [...state.rooms].sort((a, b) => {
        const indexA = roomOrder.indexOf(a.area_name.toLowerCase());
        const indexB = roomOrder.indexOf(b.area_name.toLowerCase());
        const orderA = indexA === -1 ? 999 : indexA;
        const orderB = indexB === -1 ? 999 : indexB;
        return orderA - orderB;
    });
    
    sortedRooms.forEach(room => {
        // Skip excluded rooms
        if (skipRooms.includes(room.area_name.toLowerCase())) return;
        
        // Only add nav for rooms that have controllable entities
        const hasControllable = room.entities.some(e => 
            controllableDomains.includes(e.entity_id.split('.')[0])
        );
        if (!hasControllable) return;
        
        const navBtn = document.createElement('button');
        navBtn.className = 'nav-btn room-nav';
        navBtn.dataset.section = `room-${room.area_id}`;
        navBtn.textContent = room.area_name.toUpperCase();
        navBtn.onclick = function() {
            showSection(`room-${room.area_id}`);
            playSound('audio1');
        };
        elements.mainNav.appendChild(navBtn);
    });
}

// Build section HTML for each room
function buildRoomSections() {
    if (!elements.roomSectionsContainer) return;
    if (!state.rooms || state.rooms.length === 0) return;
    
    // Clear existing room sections
    elements.roomSectionsContainer.innerHTML = '';
    
    const controllableDomains = ['light', 'switch', 'fan'];
    
    state.rooms.forEach(room => {
        const controllable = room.entities.filter(e => 
            controllableDomains.includes(e.entity_id.split('.')[0])
        );
        if (controllable.length === 0) return;
        
        const section = document.createElement('section');
        section.className = 'lcars-section';
        section.id = `section-room-${room.area_id}`;
        section.dataset.roomId = room.area_id;
        
        section.innerHTML = `
            <h2 class="section-title">${room.area_name.toUpperCase()}</h2>
            <div class="room-controls-grid" data-room-id="${room.area_id}"></div>
        `;
        
        elements.roomSectionsContainer.appendChild(section);
    });
}

// Update quick controls on Comfort page (show all controls grouped)
function updateQuickControls() {
    if (!elements.quickControlsGrid) return;
    
    if (!state.rooms || state.rooms.length === 0) {
        elements.quickControlsGrid.innerHTML = '<div class="lcars-empty">No rooms configured</div>';
        return;
    }
    
    const controllableDomains = ['light', 'switch', 'fan'];
    
    // Get all controllable entities from all rooms
    const allControllable = [];
    state.rooms.forEach(room => {
        room.entities.forEach(entity => {
            if (controllableDomains.includes(entity.entity_id.split('.')[0])) {
                allControllable.push({
                    ...entity,
                    room_name: room.area_name
                });
            }
        });
    });
    
    if (allControllable.length === 0) {
        elements.quickControlsGrid.innerHTML = '<div class="lcars-empty">No controllable devices</div>';
        return;
    }
    
    // Group by room
    const byRoom = {};
    allControllable.forEach(entity => {
        if (!byRoom[entity.room_name]) byRoom[entity.room_name] = [];
        byRoom[entity.room_name].push(entity);
    });
    
    const roomsHtml = Object.entries(byRoom).map(([roomName, entities]) => {
        entities.sort((a, b) => {
            const nameA = a.attributes?.friendly_name || a.entity_id;
            const nameB = b.attributes?.friendly_name || b.entity_id;
            return nameA.localeCompare(nameB);
        });
        
        const onCount = entities.filter(e => e.state === 'on').length;
        const statsText = `${onCount}/${entities.length} on`;
        
        const buttonsHtml = entities.map(entity => {
            const isOn = entity.state === 'on';
            const name = entity.attributes?.friendly_name || entity.entity_id.split('.')[1];
            const domain = entity.entity_id.split('.')[0];
            let icon = '⬤';
            if (domain === 'light') icon = '◉';
            else if (domain === 'fan') icon = '❋';
            
            return `
                <button class="lcars-entity-button ${isOn ? 'on' : ''}" 
                        data-entity-id="${entity.entity_id}"
                        onclick="toggleEntity('${entity.entity_id}'); playSound('audio3')">
                    <span class="icon">${icon}</span>
                    <span class="name">${truncate(name, 14)}</span>
                </button>
            `;
        }).join('');
        
        // Default to collapsed (check if NOT in expandedRooms set)
        const isCollapsed = !state.expandedRooms.has(roomName);
        
        return `
            <div class="lcars-control-room ${isCollapsed ? 'collapsed' : 'expanded'}" data-room-name="${roomName}">
                <div class="lcars-room-header" onclick="toggleQuickControlRoom(this, '${roomName.replace(/'/g, "\\'")}'); playSound('audio1')">
                    <div class="room-header-left">
                        <span class="room-name">${roomName.toUpperCase()}</span>
                    </div>
                    <span class="room-stats">${statsText}</span>
                </div>
                <div class="control-room-buttons">
                    ${buttonsHtml}
                </div>
            </div>
        `;
    }).join('');
    
    elements.quickControlsGrid.innerHTML = roomsHtml;
}

function toggleQuickControlRoom(header, roomName) {
    const room = header.closest('.lcars-control-room');
    if (room) {
        const isCurrentlyCollapsed = room.classList.contains('collapsed');
        room.classList.toggle('collapsed');
        room.classList.toggle('expanded');
        if (isCurrentlyCollapsed) {
            // Was collapsed, now expanding
            state.expandedRooms.add(roomName);
        } else {
            // Was expanded, now collapsing
            state.expandedRooms.delete(roomName);
        }
    }
}

function collapseAllRooms() {
    document.querySelectorAll('.lcars-control-room').forEach(room => {
        room.classList.add('collapsed');
        room.classList.remove('expanded');
    });
    state.expandedRooms.clear();
}

// Update individual room sections with their controls
function updateRoomSections() {
    if (!elements.roomSectionsContainer) return;
    if (!state.rooms || state.rooms.length === 0) return;
    
    const controllableDomains = ['light', 'switch', 'fan'];
    
    state.rooms.forEach(room => {
        const grid = elements.roomSectionsContainer.querySelector(
            `.room-controls-grid[data-room-id="${room.area_id}"]`
        );
        if (!grid) return;
        
        const controllable = room.entities
            .filter(e => controllableDomains.includes(e.entity_id.split('.')[0]))
            .sort((a, b) => {
                const nameA = a.attributes?.friendly_name || a.entity_id;
                const nameB = b.attributes?.friendly_name || b.entity_id;
                return nameA.localeCompare(nameB);
            });
        
        if (controllable.length === 0) {
            grid.innerHTML = '<div class="lcars-empty">No controllable devices</div>';
            return;
        }
        
        grid.innerHTML = controllable.map(entity => {
            const isOn = entity.state === 'on';
            const name = entity.attributes?.friendly_name || entity.entity_id.split('.')[1];
            const domain = entity.entity_id.split('.')[0];
            let icon = '⬤';
            if (domain === 'light') icon = '◉';
            else if (domain === 'fan') icon = '❋';
            
            return `
                <button class="lcars-entity-button ${isOn ? 'on' : ''}" 
                        data-entity-id="${entity.entity_id}"
                        onclick="toggleEntity('${entity.entity_id}'); playSound('audio3')">
                    <span class="icon">${icon}</span>
                    <span class="name">${truncate(name, 14)}</span>
                </button>
            `;
        }).join('');
    });
}

// Update button state when entity changes
function updateEntityInList(entityId) {
    const entity = state.entities[entityId];
    if (!entity) return;
    
    // Update all buttons with this entity id across all sections
    const buttons = document.querySelectorAll(`[data-entity-id="${entityId}"]`);
    buttons.forEach(btn => {
        const isOn = entity.state === 'on';
        btn.className = `lcars-entity-button ${isOn ? 'on' : ''}`;
    });
}

function formatState(entity) {
    const state = entity.state;
    const unit = entity.attributes?.unit_of_measurement;
    
    if (unit) {
        return `${state} ${unit}`;
    }
    
    return state;
}

function truncate(str, length) {
    if (!str) return '';
    return str.length > length ? str.substring(0, length) + '...' : str;
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `lcars-toast ${type}`;
    toast.textContent = message;
    
    elements.toastContainer.appendChild(toast);
    
    // Play sound for toast
    playSound('audio1');
    
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// Debounce utility
const debounceTimers = {};
function debounce(key, fn, delay) {
    clearTimeout(debounceTimers[key]);
    debounceTimers[key] = setTimeout(fn, delay);
}

// =============================================================================
// Event Listeners
// =============================================================================

// Heartbeat to keep WebSocket alive
setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
    }
}, 30000);

// Refresh camera images every 10 seconds
setInterval(() => {
    refreshCameras();
}, 10000);

// =============================================================================
// Initialization
// =============================================================================

async function init() {
    console.log('Initializing LCARS Home Assistant Dashboard...');
    
    // Update stardate display
    updateStardate();
    setInterval(updateStardate, 1000); // Update every second
    
    // Register service worker for PWA
    if ('serviceWorker' in navigator) {
        try {
            const registration = await navigator.serviceWorker.register('/service-worker.js');
            console.log('Service Worker registered:', registration.scope);
        } catch (error) {
            console.error('Service Worker registration failed:', error);
        }
    }
    
    // Initial data fetch
    await fetchDashboardState();
    
    // Connect WebSocket for real-time updates
    connectWebSocket();
    
    // Play startup beep
    playSound('audio2');
}

// Start the app
document.addEventListener('DOMContentLoaded', init);
