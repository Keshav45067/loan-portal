"""
Redis Cache Layer for Config Registry.

Handles:
- Config caching with TTL (1 hour default)
- Pub/Sub event publishing for inter-service communication
- Graceful fallback when Redis is unavailable (serves from in-memory)
"""

import json
import asyncio
from typing import Optional

import redis.asyncio as aioredis

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, get_req_id

from config import REDIS_URL, REDIS_TTL_SECONDS

logger = get_logger("config-registry")


class RedisCache:
    """Async Redis cache with Pub/Sub support."""

    def __init__(self, redis_url: str = None, ttl: int = None):
        self._url = redis_url or REDIS_URL
        self._ttl = ttl or REDIS_TTL_SECONDS
        self._client: Optional[aioredis.Redis] = None
        self._available = False

    async def connect(self):
        """Connect to Redis. Falls back gracefully if unavailable."""
        try:
            self._client = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
            )
            # Test connection
            await self._client.ping()
            self._available = True
            logger.info("Redis connected", details={"url": self._url, "ttl": self._ttl})
        except Exception as e:
            self._available = False
            logger.warning(f"Redis unavailable, using in-memory only: {e}",
                           error=str(e))

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            logger.info("Redis connection closed")

    @property
    def is_available(self) -> bool:
        return self._available

    # ─── Cache Operations ───

    async def get(self, key: str) -> Optional[str]:
        """Get value from cache. Returns None if not found or Redis unavailable."""
        if not self._available:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.warning(f"Redis GET failed: {e}", error=str(e))
            return None

    async def set(self, key: str, value: str, ttl: int = None):
        """Set value in cache with TTL."""
        if not self._available:
            return
        try:
            await self._client.set(key, value, ex=ttl or self._ttl)
        except Exception as e:
            logger.warning(f"Redis SET failed: {e}", error=str(e))

    async def delete(self, key: str):
        """Delete a key from cache."""
        if not self._available:
            return
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.warning(f"Redis DELETE failed: {e}", error=str(e))

    async def invalidate_scheme(self, scheme_id: str):
        """Invalidate all cached data for a scheme."""
        if not self._available:
            return
        try:
            keys = []
            async for key in self._client.scan_iter(f"config:{scheme_id}:*"):
                keys.append(key)
            if keys:
                await self._client.delete(*keys)
                logger.info(f"Invalidated {len(keys)} cache keys for scheme {scheme_id}",
                            scheme_id=scheme_id)
        except Exception as e:
            logger.warning(f"Redis invalidate failed: {e}", error=str(e))

    # ─── Scheme-specific cache helpers ───

    async def get_scheme_config(self, scheme_id: str) -> Optional[dict]:
        """Get full scheme config from cache."""
        raw = await self.get(f"config:{scheme_id}:full")
        if raw:
            return json.loads(raw)
        return None

    async def set_scheme_config(self, scheme_id: str, config: dict):
        """Cache full scheme config."""
        await self.set(f"config:{scheme_id}:full", json.dumps(config, ensure_ascii=False))

    async def get_interview_graph(self, scheme_id: str) -> Optional[dict]:
        """Get interview graph from cache."""
        raw = await self.get(f"config:{scheme_id}:graph")
        if raw:
            return json.loads(raw)
        return None

    async def set_interview_graph(self, scheme_id: str, graph: dict):
        """Cache interview graph."""
        await self.set(f"config:{scheme_id}:graph", json.dumps(graph, ensure_ascii=False))

    # ─── Pub/Sub Operations ───

    async def publish(self, channel: str, event: dict):
        """Publish an event to a Redis Pub/Sub channel."""
        if not self._available:
            logger.warning("Redis unavailable, event not published",
                           details={"channel": channel})
            return
        try:
            message = json.dumps(event, ensure_ascii=False, default=str)
            await self._client.publish(channel, message)
            logger.debug(f"Published event to {channel}",
                          details={"event_type": event.get("event", "unknown")})
        except Exception as e:
            logger.error(f"Redis PUBLISH failed: {e}", error=str(e))

    async def subscribe(self, *channels):
        """
        Subscribe to Redis Pub/Sub channels.
        Returns an async iterator that yields messages.
        """
        if not self._available:
            logger.warning("Redis unavailable, cannot subscribe")
            return

        pubsub = self._client.pubsub()
        await pubsub.subscribe(*channels)
        logger.info(f"Subscribed to channels: {channels}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    yield {
                        "channel": message["channel"],
                        "data": data,
                    }
        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.close()


# ─── Pub/Sub Channel Definitions ───
CHANNELS = {
    "extraction_update": "events:extraction_update",
    "document_verified": "events:document_verified",
    "document_extracted": "events:document_extracted",
    "session_ended": "events:session_ended",
}
