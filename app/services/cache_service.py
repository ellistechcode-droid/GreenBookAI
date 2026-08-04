from cachetools import TTLCache
from threading import Lock
from typing import Any, Optional


class CacheService:
    """
    Central in-memory cache for GreenBookAI.

    Each data source has its own cache and expiration time because
    weather, flights, lodging, and advisories become stale at
    different rates.
    """

    def __init__(self):
        self._lock = Lock()

        # 1 hour
        self.weather_cache = TTLCache(maxsize=500, ttl=60 * 60)

        # 20 minutes
        self.flight_cache = TTLCache(maxsize=500, ttl=20 * 60)

        # 1 hour
        self.lodging_cache = TTLCache(maxsize=500, ttl=60 * 60)

        # 24 hours
        self.advisory_cache = TTLCache(maxsize=250, ttl=24 * 60 * 60)

        # 7 days
        self.geocoding_cache = TTLCache(maxsize=1000, ttl=7 * 24 * 60 * 60)

        # 24 hours
        self.embedding_cache = TTLCache(maxsize=1000, ttl=24 * 60 * 60)

    def get(self, cache_name: str, key: str) -> Optional[Any]:
        """
        Returns a cached value or None when the key is not cached.
        """
        cache = self._get_cache(cache_name)

        with self._lock:
            return cache.get(key)

    def set(self, cache_name: str, key: str, value: Any) -> None:
        """
        Stores a value in the selected cache.
        """
        cache = self._get_cache(cache_name)

        with self._lock:
            cache[key] = value

    def delete(self, cache_name: str, key: str) -> None:
        """
        Removes one cached value.
        """
        cache = self._get_cache(cache_name)

        with self._lock:
            cache.pop(key, None)

    def clear(self, cache_name: Optional[str] = None) -> None:
        """
        Clears one cache or every cache.
        """
        with self._lock:
            if cache_name:
                self._get_cache(cache_name).clear()
                return

            for cache in self._all_caches():
                cache.clear()

    def _get_cache(self, cache_name: str) -> TTLCache:
        caches = {
            "weather": self.weather_cache,
            "flight": self.flight_cache,
            "lodging": self.lodging_cache,
            "advisory": self.advisory_cache,
            "geocoding": self.geocoding_cache,
            "embedding": self.embedding_cache,
        }

        if cache_name not in caches:
            raise ValueError(f"Unknown cache name: {cache_name}")

        return caches[cache_name]

    def _all_caches(self):
        return [
            self.weather_cache,
            self.flight_cache,
            self.lodging_cache,
            self.advisory_cache,
            self.geocoding_cache,
            self.embedding_cache,
        ]


cache_service = CacheService()