"""Fixtures: a fake ShowPilot server built from a real /api/state snapshot."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import sys

import pytest
import pytest_socket

from homeassistant.util import dt as dt_util

if sys.platform == "win32":
    # Windows' event loop wakes itself through an AF_INET socket pair, which
    # pytest-socket blocks. HTTP still goes through aioclient_mock.
    pytest_socket.disable_socket = lambda *a, **k: None

URL = "http://showpilot.test:3100"
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeServer:
    def __init__(self, aioclient_mock) -> None:
        self.mock = aioclient_mock
        self.state: dict[str, Any] = json.loads((FIX / "state_live.json").read_text("utf-8"))
        self.state["showName"] = "Test Show"
        self.stats: dict[str, Any] = json.loads((FIX / "page_stats_live.json").read_text("utf-8"))
        self.token = "good-token"
        self.last_seen = dt_util.utcnow().isoformat()
        self.categories = [{"name": "Kids", "enabled": 1}, {"name": "Classics", "enabled": 0}]
        self.pages = [{"name": "Main", "active": 1}, {"name": "Off season", "active": 0}]
        self.posts: list[tuple[str, Any]] = []
        self.down = False
        self.install()

    def song(self, idx: int) -> dict[str, Any]:
        return self.state["sequences"][idx]

    def play(self, idx: int | None) -> None:
        if idx is None:
            self.state.update(nowPlaying=None, nowPlayingDisplayName=None, nowPlayingArtist="",
                              nowPlayingStartedAtIso=None, nowPlayingDurationSeconds=None)
            return
        s = self.song(idx)
        self.state.update(
            nowPlaying=s["name"], nowPlayingDisplayName=s["display_name"], nowPlayingArtist=s["artist"],
            nowPlayingImageUrl=s["image_url"], nowPlayingStartedAtIso="2026-11-21T11:00:00Z",
            nowPlayingDurationSeconds=s["duration_seconds"],
        )
        self.state["queue"] = [q for q in self.state["queue"] if q["sequence_name"] != s["name"]]

    def request(self, idx: int, at: str) -> None:
        self.state["queue"].append({"sequence_name": self.song(idx)["name"], "requested_at": at, "handed_off_at": None})
        self.stats["tonight"]["requests"] += 1

    def _auth(self, headers) -> bool:
        return (headers or {}).get("Authorization") == f"Bearer {self.token}"

    def install(self) -> None:
        from aiohttp import ClientConnectionError
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        srv = self

        def respond(method, url, data, headers, status=200):
            return AiohttpClientMockResponse(method, url, status=status, json=data, headers=headers)

        def make(path: str, method: str):
            async def handler(m, url, data):
                if srv.down:
                    raise ClientConnectionError("down")
                hdrs = srv._last_headers
                if path.startswith("/api/plugin") and not srv._auth(hdrs):
                    return respond(m, url, {"error": "Invalid or missing bearer token"}, None, 401)
                if method == "POST":
                    srv.posts.append((path, data))
                    if path == "/api/plugin/viewer-mode":
                        srv.state["viewerControlMode"] = data["mode"]
                    elif path == "/api/plugin/category":
                        for c in srv.categories:
                            if c["name"] == data["name"]:
                                c["enabled"] = 1 if data["enabled"] else 0
                    elif path == "/api/plugin/queue/clear":
                        n = len(srv.state["queue"])
                        srv.state["queue"] = []
                        return respond(m, url, {"ok": True, "cleared": n}, None)
                    return respond(m, url, {"ok": True}, None)
                body = {
                    "/health": {"ok": True, "version": "0.33.284"},
                    "/api/state": srv.state,
                    "/api/page-stats": srv.stats,
                    "/api/plugin/health": {"plugin": {"lastSeen": srv.last_seen, "version": "0.14.31"}},
                    "/api/plugin/state": {"mode": srv.state["viewerControlMode"], "interruptSchedule": True, "peek": True},
                    "/api/plugin/categories": {"categories": srv.categories},
                    "/api/plugin/viewer-pages": {"pages": srv.pages},
                }[path]
                return respond(m, url, copy.deepcopy(body), None)

            return handler

        for path in ("/health", "/api/state", "/api/page-stats", "/api/plugin/health",
                     "/api/plugin/categories", "/api/plugin/viewer-pages"):
            self.mock.get(f"{URL}{path}", side_effect=make(path, "GET"))
        self.mock.get(f"{URL}/api/plugin/state?peek=1", side_effect=make("/api/plugin/state", "GET"))
        for path in ("/api/plugin/viewer-mode", "/api/plugin/queue/clear", "/api/plugin/category",
                     "/api/plugin/viewer-page"):
            self.mock.post(f"{URL}{path}", side_effect=make(path, "POST"))

    _last_headers: dict | None = None


@pytest.fixture
def server(aioclient_mock) -> FakeServer:
    srv = FakeServer(aioclient_mock)
    # Record request headers: wrap the mock's match so handlers can check auth.
    orig = aioclient_mock.match_request

    async def match_request(method, url, *, data=None, auth=None, params=None, headers=None, **kw):
        srv._last_headers = headers
        return await orig(method, url, data=data, auth=auth, params=params, headers=headers, **kw)

    aioclient_mock.match_request = match_request
    return srv
