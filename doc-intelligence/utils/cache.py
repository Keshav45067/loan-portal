import json
from typing import Optional, Any, Dict
import redis.asyncio as aioredis
from log_utils.logger import get_logger

logger = get_logger("doc-intelligence-cache")

class DocIntelCache:
    """Caching layer for doc-intelligence with local memory and Redis options."""

    def __init__(self, redis_url: str, ttl: int):
        self._url = redis_url
        self._ttl = ttl
        self._client: Optional[aioredis.Redis] = None
        self._available = False
        self._local: Dict[str, Any] = {}

    async def connect(self):
        """Connect to Redis. Falls back to local memory if Redis is down."""
        try:
            self._client = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3
            )
            await self._client.ping()
            self._available = True
            logger.info("Redis cache connected for doc-intelligence", details={"url": self._url})
        except Exception as e:
            self._available = False
            logger.warning(f"Redis unavailable for doc-intelligence, using local memory cache only: {e}")

    async def close(self):
        """Close connection to Redis."""
        if self._client:
            await self._client.close()

    async def get_requirement(self, scheme_id: str, doc_type: str) -> Optional[dict]:
        """Get document requirements from local cache or Redis."""
        local_key = f"{scheme_id}:{doc_type}"
        
        # 1. Check local in-memory cache
        if local_key in self._local:
            return self._local[local_key]

        # 2. Check Redis cache
        if self._available:
            try:
                redis_key = f"doc_intel:{scheme_id}:{doc_type}:req"
                raw = await self._client.get(redis_key)
                if raw:
                    req = json.loads(raw)
                    self._local[local_key] = req  # Populate local
                    return req
            except Exception as e:
                logger.warning(f"Redis GET failed in doc-intelligence cache: {e}")

        return None

    async def set_requirement(self, scheme_id: str, doc_type: str, requirement: dict):
        """Set document requirements in both local cache and Redis."""
        local_key = f"{scheme_id}:{doc_type}"
        self._local[local_key] = requirement

        if self._available:
            try:
                redis_key = f"doc_intel:{scheme_id}:{doc_type}:req"
                await self._client.set(
                    redis_key, 
                    json.dumps(requirement, ensure_ascii=False), 
                    ex=self._ttl
                )
            except Exception as e:
                logger.warning(f"Redis SET failed in doc-intelligence cache: {e}")
