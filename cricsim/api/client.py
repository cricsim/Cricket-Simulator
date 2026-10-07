"""Low-level HTTP client for the Cricbuzz Cricket API on RapidAPI.

Handles the two required headers, a per-endpoint disk cache, request throttling,
retries with backoff, and quota tracking from RapidAPI's rate-limit headers.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from cricsim import __version__

USER_AGENT = f"cricsim/{__version__} (+https://github.com/)"

# Cache policies: a TTL in seconds, or one of these sentinels.
PERMANENT = -1  # finished-match data: never re-fetched
NO_CACHE = 0  # live data: always fetched, never stored

# RapidAPI reports quota with different header names depending on the plan.
_REMAINING_HEADERS = (
    "x-ratelimit-requests-remaining",
    "x-ratelimit-rapid-free-plans-hard-limit-remaining",
)
_LIMIT_HEADERS = (
    "x-ratelimit-requests-limit",
    "x-ratelimit-rapid-free-plans-hard-limit-limit",
)


class ApiError(RuntimeError):
    pass


class QuotaGuardError(ApiError):
    """Raised before a call that would push the remaining quota below the reserve."""


class OfflineCacheMiss(ApiError):
    pass


@dataclass
class Quota:
    remaining: int | None = None
    limit: int | None = None

    def update(self, headers: httpx.Headers) -> None:
        for name in _REMAINING_HEADERS:
            if name in headers:
                self.remaining = int(headers[name])
                break
        for name in _LIMIT_HEADERS:
            if name in headers:
                self.limit = int(headers[name])
                break


@dataclass
class CricbuzzClient:
    api_key: str | None
    host: str
    cache_dir: Path
    offline: bool = False
    requests_per_second: float = 4.0
    quota_reserve: int = 5
    max_retries: int = 4
    calls_made: int = 0
    quota: Quota = field(default_factory=Quota)
    _last_call: float = 0.0
    _http: httpx.Client | None = None

    # ---- public -------------------------------------------------------------------------

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        ttl: int = 3600,
        store_if: Callable[[Any], bool] | None = None,
    ) -> Any:
        """GET `path` and return parsed JSON (None for an empty 204 response).

        ttl: seconds to keep the response, PERMANENT or NO_CACHE.
        store_if: optional predicate; when it returns False the response is not cached
            (for example a scorecard of a match that is still in progress).
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        cache_file = self._cache_path(path, params)
        if ttl != NO_CACHE or self.offline:
            # Offline mode serves any cached response, however old.
            cached = self._read_cache(cache_file, ttl, allow_stale=self.offline)
            if cached is not None:
                return cached["data"]
        if self.offline:
            raise OfflineCacheMiss(f"offline mode: no cached response for {path}")

        data = self._fetch(path, params)
        if ttl != NO_CACHE and (store_if is None or store_if(data)):
            self._write_cache(cache_file, path, params, data, ttl)
        return data

    def is_cached(self, path: str, params: dict[str, Any] | None = None, ttl: int = 3600) -> bool:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        entry = self._read_cache(self._cache_path(path, params), ttl, allow_stale=self.offline)
        return entry is not None

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    # ---- internals ----------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        if not self.api_key:
            raise ApiError("RAPIDAPI_KEY is not set. Run `cricsim init` or add it to .env.")
        if self._http is None:
            self._http = httpx.Client(
                base_url=f"https://{self.host}",
                headers={
                    "x-rapidapi-key": self.api_key,
                    "x-rapidapi-host": self.host,
                    "User-Agent": USER_AGENT,
                },
                timeout=30.0,
            )
        return self._http

    def _throttle(self) -> None:
        min_gap = 1.0 / self.requests_per_second
        wait = self._last_call + min_gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _fetch(self, path: str, params: dict[str, Any]) -> Any:
        if self.quota.remaining is not None and self.quota.remaining <= self.quota_reserve:
            raise QuotaGuardError(
                f"only {self.quota.remaining} API calls left this period "
                f"(reserve {self.quota_reserve}); stopping before {path}"
            )
        http = self._client()
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise ApiError(f"network error calling {path}: {exc}") from exc
                time.sleep(2**attempt)
                continue
            self.calls_made += 1
            self.quota.update(resp.headers)
            if resp.status_code == 204:
                return None
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    raise ApiError(f"{resp.status_code} from {path} after retries")
                retry_after = float(resp.headers.get("retry-after", 2**attempt))
                time.sleep(min(retry_after, 30))
                continue
            if resp.status_code in (401, 403):
                raise ApiError(
                    f"{resp.status_code} from {path}: check RAPIDAPI_KEY and that you are "
                    "subscribed to the Cricbuzz Cricket API on RapidAPI"
                )
            if resp.status_code >= 400:
                raise ApiError(f"{resp.status_code} from {path}: {resp.text[:200]}")
            return resp.json()
        raise ApiError(f"unreachable: {path}")

    def _cache_path(self, path: str, params: dict[str, Any]) -> Path:
        key = path + ("?" + urlencode(sorted(params.items())) if params else "")
        digest = hashlib.sha1(key.encode()).hexdigest()[:16]
        slug = path.strip("/").replace("/", "_")[:80]
        return self.cache_dir / f"{slug}__{digest}.json"

    @staticmethod
    def _read_cache(cache_file: Path, ttl: int, allow_stale: bool = False) -> dict | None:
        if not cache_file.is_file():
            return None
        try:
            entry = json.loads(cache_file.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        stored_ttl = entry.get("ttl", ttl)
        if stored_ttl == PERMANENT or allow_stale:
            return entry
        if time.time() - entry.get("fetched_at", 0) <= min(ttl, stored_ttl):
            return entry
        return None

    @staticmethod
    def _write_cache(cache_file: Path, path: str, params: dict, data: Any, ttl: int) -> None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {"path": path, "params": params, "fetched_at": time.time(), "ttl": ttl,
                 "data": data}
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry))
        tmp.replace(cache_file)
