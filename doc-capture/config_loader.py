import json
import time
from typing import Dict, Optional, Tuple
import psycopg2
from psycopg2 import pool
from config import DATABASE_URL, CONFIG_CACHE_TTL_SECONDS
from log_utils.logger import get_logger

logger = get_logger("doc-capture")

class ConfigLoader:
    def __init__(self):
        # Initialize DB pool
        conn_url = DATABASE_URL
        if "postgresql://" in conn_url or "postgres://" in conn_url:
            if "?" in conn_url:
                conn_url += "&keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3"
            else:
                conn_url += "?keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3"
        
        self.db_pool = psycopg2.pool.ThreadedConnectionPool(1, 10, conn_url)
        
        # Memory Cache: {key: (timestamp, data)}
        self._memory_cache: Dict[str, Tuple[float, dict]] = {}

    def _get_from_cache(self, cache_key: str) -> Optional[dict]:
        if cache_key in self._memory_cache:
            timestamp, data = self._memory_cache[cache_key]
            if time.time() - timestamp < CONFIG_CACHE_TTL_SECONDS:
                return data
            else:
                del self._memory_cache[cache_key]
        return None

    def _set_cache(self, cache_key: str, data: dict):
        self._memory_cache[cache_key] = (time.time(), data)

    def get_scheme(self, scheme_id: str) -> Optional[dict]:
        cache_key = f"scheme_{scheme_id}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        conn = None
        try:
            conn = self.db_pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT json FROM schemes_json WHERE id = %s", (scheme_id,))
                row = cur.fetchone()
                if row and row[0]:
                    data = row[0]
                    if isinstance(data, str):
                        data = json.loads(data)
                    self._set_cache(cache_key, data)
                    return data
        except Exception as e:
            logger.error(f"Failed to load scheme {scheme_id}: {e}")
        finally:
            if conn:
                self.db_pool.putconn(conn)
        
        return None

    def get_document(self, document_id: str) -> Optional[dict]:
        cache_key = f"document_{document_id}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        conn = None
        try:
            conn = self.db_pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT json FROM documents_json WHERE id = %s", (document_id,))
                row = cur.fetchone()
                if row and row[0]:
                    data = row[0]
                    if isinstance(data, str):
                        data = json.loads(data)
                    self._set_cache(cache_key, data)
                    return data
        except Exception as e:
            logger.error(f"Failed to load document {document_id}: {e}")
        finally:
            if conn:
                self.db_pool.putconn(conn)
        
        return None

# Singleton instance
config_loader = ConfigLoader()
