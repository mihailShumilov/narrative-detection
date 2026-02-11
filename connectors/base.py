"""Base connector interface."""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.models import SignalEvent
from pipeline.logging import get_logger

logger = get_logger(__name__)

CACHE_DIR = Path("./data/cache")


class BaseConnector(ABC):
    """Base class for all data source connectors."""

    name: str = "base"
    rate_limit_rps: float = 5.0

    def __init__(self, config: dict, cache_enabled: bool = True):
        self.config = config
        self.cache_enabled = cache_enabled
        self._last_request_time = 0.0
        self._client = httpx.Client(timeout=30.0)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _rate_limit(self):
        """Simple rate limiter."""
        now = time.time()
        min_interval = 1.0 / self.rate_limit_rps
        elapsed = now - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _cache_key(self, key: str) -> Path:
        """Generate cache file path."""
        import hashlib

        h = hashlib.sha256(f"{self.name}:{key}".encode()).hexdigest()[:16]
        return CACHE_DIR / f"{self.name}_{h}.json"

    def _get_cached(self, key: str) -> Optional[list[dict]]:
        """Retrieve cached data if available and fresh."""
        if not self.cache_enabled:
            return None
        cache_path = self._cache_key(key)
        if cache_path.exists():
            data = json.loads(cache_path.read_text())
            cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
            ttl_hours = self.config.get("cache", {}).get("ttl_hours", 336)
            age_hours = (
                datetime.now() - cached_at.replace(tzinfo=None)
            ).total_seconds() / 3600
            if age_hours < ttl_hours:
                logger.info(
                    "cache_hit",
                    connector=self.name,
                    key=key,
                    age_hours=round(age_hours, 1),
                )
                return data.get("events", [])
        return None

    def _set_cached(self, key: str, events: list[dict]):
        """Store data in cache."""
        if not self.cache_enabled:
            return
        cache_path = self._cache_key(key)
        data = {"cached_at": datetime.now().isoformat(), "events": events}
        cache_path.write_text(json.dumps(data, indent=2, default=str))
        logger.info(
            "cache_set", connector=self.name, key=key, event_count=len(events)
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    def _fetch_url(self, url: str, headers: dict | None = None, params: dict | None = None) -> httpx.Response:
        """Fetch URL with rate limiting and retries."""
        self._rate_limit()
        logger.debug("fetching_url", connector=self.name, url=url)
        response = self._client.get(url, headers=headers or {}, params=params or {})
        response.raise_for_status()
        return response

    @abstractmethod
    def fetch(
        self, window_start: datetime, window_end: datetime
    ) -> list[SignalEvent]:
        """Fetch events within the given time window."""
        ...

    def close(self):
        self._client.close()
