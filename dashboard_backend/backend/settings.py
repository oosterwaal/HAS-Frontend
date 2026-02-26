"""
Settings module - loads configuration from environment variables.
"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


class Settings:
    """Application settings loaded from environment."""
    
    # Home Assistant connection (support both HA_URL and HA_BASE_URL)
    HA_URL: str = os.getenv("HA_URL") or os.getenv("HA_BASE_URL", "http://homeassistant.local:8123").rstrip("/")
    HA_TOKEN: str = os.getenv("HA_TOKEN", "")
    
    # WebSocket URL derived from HA_URL
    @property
    def HA_WS_URL(self) -> str:
        """Convert HTTP URL to WebSocket URL."""
        url = self.HA_URL.replace("https://", "wss://").replace("http://", "ws://")
        return f"{url}/api/websocket"
    
    # Server settings
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Cache settings
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "30"))
    
    # Energy tracking
    ENERGY_ENTITIES: list[str] = [
        e.strip() for e in os.getenv("ENERGY_ENTITIES", "").split(",") if e.strip()
    ]
    
    # Climate/comfort entities
    CLIMATE_ENTITIES: list[str] = [
        e.strip() for e in os.getenv("CLIMATE_ENTITIES", "").split(",") if e.strip()
    ]
    
    # Entity domains to subscribe to (empty = all)
    SUBSCRIBE_DOMAINS: list[str] = [
        e.strip() for e in os.getenv("SUBSCRIBE_DOMAINS", "").split(",") if e.strip()
    ]
    
    def validate(self) -> tuple[bool, Optional[str]]:
        """Validate required settings."""
        if not self.HA_TOKEN:
            return False, "HA_TOKEN is required"
        if not self.HA_URL:
            return False, "HA_URL is required"
        return True, None


settings = Settings()
