# Home Assistant Dashboard

A local microservice (FastAPI) + PWA for controlling Home Assistant from an Android phone/tablet.

## Features

- **Real-time updates** via WebSocket connection to Home Assistant
- **Offline-capable PWA** that runs in the browser
- **Comfort scoring** based on temperature and humidity sensors
- **Energy monitoring** with aggregated consumption data
- **Room grouping** for organized entity management
- **Quick controls** for lights and switches
- **Full entity browser** with search and filtering

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Android Phone/Tablet                      │
│  ┌─────────────┐     HTTP/WS      ┌────────────────────┐   │
│  │   Browser   │ ◄──────────────► │  FastAPI Backend   │   │
│  │    (PWA)    │   localhost:8000 │  (Python/uvicorn)  │   │
│  └─────────────┘                  └─────────┬──────────┘   │
└─────────────────────────────────────────────┼───────────────┘
                                              │ WebSocket + REST
                                              ▼
                                    ┌──────────────────┐
                                    │  Home Assistant  │
                                    │   (on your LAN)  │
                                    └──────────────────┘
```

## Prerequisites

- Python 3.11+
- Home Assistant instance accessible on your LAN
- Long-lived access token from Home Assistant

## Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd dashboard_backend
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows
```

### 3. Install dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Configure environment

Create a `.env` file in the project root (copy from `.env.example`):

```bash
# Required
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token

# Optional
HOST=127.0.0.1
PORT=8000
CACHE_TTL_SECONDS=30
ENERGY_ENTITIES=sensor.energy_total
CLIMATE_ENTITIES=sensor.living_room_temp
SUBSCRIBE_DOMAINS=light,switch,climate,sensor
```

**Getting a Long-Lived Access Token:**
1. Go to your Home Assistant UI
2. Click on your profile (bottom left)
3. Scroll down to "Long-Lived Access Tokens"
4. Create a new token and copy it

### 5. Run the server

```bash
python -m backend
```

Or with options:

```bash
python -m backend --host 0.0.0.0 --port 8080 --reload
```

### 6. Open in browser

Navigate to `http://127.0.0.1:8000` in your phone's browser.

**Install as PWA:**
1. Open the URL in Chrome/Edge
2. Tap the menu (⋮) 
3. Select "Add to Home screen" or "Install app"

## Running on Android (Termux)

You can run this directly on Android using [Termux](https://termux.dev/):

```bash
# Install Termux from F-Droid (not Play Store)

# Install Python
pkg install python

# Clone and setup
git clone <repo-url>
cd dashboard_backend
pip install -r backend/requirements.txt

# Create .env file
nano .env

# Run (will start on boot if you add to ~/.bashrc)
python -m backend
```

## API Endpoints

### Health & Diagnostics
- `GET /health` - Health check
- `GET /diagnostics` - Full diagnostics report

### Entity States
- `GET /api/states` - All entity states
- `GET /api/states/{entity_id}` - Single entity state
- `GET /api/states/domain/{domain}` - Entities by domain

### Dashboard (Computed)
- `GET /api/dashboard` - Full dashboard state
- `GET /api/comfort` - Comfort score
- `GET /api/energy` - Energy summary
- `GET /api/rooms` - Room groupings
- `GET /api/summary` - Entity counts by domain

### Service Calls
- `POST /api/services/call` - Generic service call
- `POST /api/services/{domain}/{service}` - Simplified call
- `POST /api/entity/{entity_id}/turn_on` - Turn on
- `POST /api/entity/{entity_id}/turn_off` - Turn off
- `POST /api/entity/{entity_id}/toggle` - Toggle

### Climate
- `POST /api/climate/{entity_id}/set_temperature` - Set temp
- `POST /api/climate/{entity_id}/set_hvac_mode` - Set mode

### WebSocket
- `WS /ws` - Real-time state updates

## Project Structure

```
dashboard_backend/
├── backend/
│   ├── __main__.py      # Entry point
│   ├── app.py           # FastAPI application
│   ├── models.py        # Pydantic models
│   ├── settings.py      # Configuration loader
│   ├── ha_ws.py         # WebSocket client for HA
│   ├── ha_rest.py       # REST client for HA
│   ├── compute.py       # Aggregation/comfort/energy
│   ├── diagnostics.py   # Health checks
│   └── requirements.txt
├── frontend/
│   ├── index.html       # PWA entry point
│   ├── app.js           # Frontend JavaScript
│   ├── style.css        # Mobile-first styles
│   ├── manifest.json    # PWA manifest
│   └── service-worker.js
└── .env.example
```

## Home Assistant API Reference

This project uses the official Home Assistant APIs:

- **WebSocket API**: `/api/websocket`
  - [Documentation](https://developers.home-assistant.io/docs/api/websocket)
  - Used for: Real-time state updates, authentication

- **REST API**: `/api/*`
  - [Documentation](https://developers.home-assistant.io/docs/api/rest)
  - Used for: Service calls, state queries

## License

MIT
