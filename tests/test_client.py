"""HTTP client behaviour with a mock transport (no key or network needed)."""

import httpx
import pytest

from cricsim.api import client as client_mod
from cricsim.api.client import (
    NO_CACHE,
    PERMANENT,
    ApiError,
    CricbuzzClient,
    OfflineCacheMiss,
    QuotaGuardError,
)


def make_client(tmp_path, handler, **kw) -> tuple[CricbuzzClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    c = CricbuzzClient("test-key", "example.test", tmp_path, requests_per_second=1000, **kw)
    c._http = httpx.Client(base_url="https://example.test",
                           transport=httpx.MockTransport(record))
    return c, seen


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)


def ok(payload=None, headers=None):
    return lambda req: httpx.Response(200, json=payload or {"ok": True}, headers=headers or {})


def test_permanent_cache_avoids_second_call(tmp_path):
    c, seen = make_client(tmp_path, ok({"a": 1}))
    assert c.get("/x", ttl=PERMANENT) == {"a": 1}
    assert c.get("/x", ttl=PERMANENT) == {"a": 1}
    assert len(seen) == 1 and c.calls_made == 1


def test_query_params_are_part_of_cache_key(tmp_path):
    c, seen = make_client(
        tmp_path, lambda r: httpx.Response(200, json={"iid": r.url.params["iid"]}))
    assert c.get("/b", {"iid": 1}, ttl=PERMANENT) == {"iid": "1"}
    assert c.get("/b", {"iid": 2}, ttl=PERMANENT) == {"iid": "2"}
    assert len(seen) == 2


def test_no_cache_always_fetches(tmp_path):
    c, seen = make_client(tmp_path, ok())
    c.get("/live", ttl=NO_CACHE)
    c.get("/live", ttl=NO_CACHE)
    assert len(seen) == 2
    assert not list(tmp_path.glob("*.json"))


def test_store_if_false_is_not_cached(tmp_path):
    c, seen = make_client(tmp_path, ok({"ismatchcomplete": False}))
    c.get("/scard", ttl=PERMANENT, store_if=lambda d: d["ismatchcomplete"])
    c.get("/scard", ttl=PERMANENT, store_if=lambda d: d["ismatchcomplete"])
    assert len(seen) == 2


def test_ttl_expiry(tmp_path, monkeypatch):
    c, seen = make_client(tmp_path, ok())
    now = [1_000_000.0]
    monkeypatch.setattr(client_mod.time, "time", lambda: now[0])
    c.get("/u", ttl=3600)
    now[0] += 3000
    c.get("/u", ttl=3600)
    assert len(seen) == 1
    now[0] += 1000
    c.get("/u", ttl=3600)
    assert len(seen) == 2


def test_offline_miss_raises_and_hit_works(tmp_path):
    c, _ = make_client(tmp_path, ok({"v": 1}))
    c.get("/o", ttl=PERMANENT)
    off = CricbuzzClient(None, "example.test", tmp_path, offline=True)
    assert off.get("/o", ttl=PERMANENT) == {"v": 1}
    with pytest.raises(OfflineCacheMiss):
        off.get("/missing", ttl=PERMANENT)


@pytest.mark.parametrize(
    "prefix", ["x-ratelimit-requests", "x-ratelimit-rapid-free-plans-hard-limit"])
def test_quota_headers(tmp_path, prefix):
    headers = {f"{prefix}-remaining": "42", f"{prefix}-limit": "500"}
    c, _ = make_client(tmp_path, ok(headers=headers))
    c.get("/q", ttl=NO_CACHE)
    assert (c.quota.remaining, c.quota.limit) == (42, 500)


def test_quota_guard_stops_before_call(tmp_path):
    c, seen = make_client(tmp_path, ok(headers={"x-ratelimit-requests-remaining": "3"}),
                          quota_reserve=5)
    c.get("/q", ttl=NO_CACHE)
    with pytest.raises(QuotaGuardError):
        c.get("/q2", ttl=NO_CACHE)
    assert len(seen) == 1


def test_cached_reads_work_when_quota_exhausted(tmp_path):
    c, _ = make_client(tmp_path, ok({"v": 1}, headers={"x-ratelimit-requests-remaining": "0"}))
    c.get("/c", ttl=PERMANENT)
    assert c.get("/c", ttl=PERMANENT) == {"v": 1}


def test_retries_429_then_succeeds(tmp_path):
    responses = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json={"v": 2})])
    c, seen = make_client(tmp_path, lambda r: next(responses))
    assert c.get("/r", ttl=NO_CACHE) == {"v": 2}
    assert len(seen) == 3


def test_gives_up_after_max_retries(tmp_path):
    c, seen = make_client(tmp_path, lambda r: httpx.Response(500), max_retries=2)
    with pytest.raises(ApiError):
        c.get("/r", ttl=NO_CACHE)
    assert len(seen) == 3


def test_auth_error_message(tmp_path):
    c, _ = make_client(tmp_path, lambda r: httpx.Response(403, text="nope"))
    with pytest.raises(ApiError, match="subscribed"):
        c.get("/a", ttl=NO_CACHE)


def test_204_returns_none_and_is_cached_for_its_ttl(tmp_path):
    c, seen = make_client(tmp_path, lambda r: httpx.Response(204))
    assert c.get("/hub", ttl=3600) is None
    assert c.get("/hub", ttl=3600) is None
    assert len(seen) == 1


def test_missing_key_is_a_clear_error(tmp_path):
    c = CricbuzzClient(None, "example.test", tmp_path)
    with pytest.raises(ApiError, match="RAPIDAPI_KEY"):
        c.get("/x", ttl=NO_CACHE)


def test_real_client_sends_rapidapi_and_user_agent_headers(tmp_path, monkeypatch):
    seen: list[httpx.Request] = []
    real_client = httpx.Client

    def factory(**kw):
        return real_client(transport=httpx.MockTransport(
            lambda r: seen.append(r) or httpx.Response(200, json={})), **kw)

    monkeypatch.setattr(client_mod.httpx, "Client", factory)
    c = CricbuzzClient("k", "cricbuzz-cricket.p.rapidapi.com", tmp_path)
    c.get("/h", {"iid": 1}, ttl=NO_CACHE)
    req = seen[0]
    assert req.headers["x-rapidapi-key"] == "k"
    assert req.headers["x-rapidapi-host"] == "cricbuzz-cricket.p.rapidapi.com"
    assert req.headers["user-agent"].startswith("cricsim/")
    assert str(req.url) == "https://cricbuzz-cricket.p.rapidapi.com/h?iid=1"


def test_offline_serves_stale_entries(tmp_path, monkeypatch):
    c, _ = make_client(tmp_path, ok({"v": 1}))
    now = [1_000_000.0]
    monkeypatch.setattr(client_mod.time, "time", lambda: now[0])
    c.get("/s", ttl=60)
    now[0] += 10_000
    off = CricbuzzClient(None, "example.test", tmp_path, offline=True)
    assert off.get("/s", ttl=60) == {"v": 1}
    assert off.is_cached("/s", ttl=60)
    assert not c.is_cached("/s", ttl=60)  # online: expired
