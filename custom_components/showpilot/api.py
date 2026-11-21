"""Small async client for a ShowPilot server."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=10)


class ShowPilotError(Exception):
    """Base error."""


class ShowPilotConnectionError(ShowPilotError):
    """The server can't be reached or answered badly."""


class ShowPilotAuthError(ShowPilotError):
    """The show token was refused."""


class ShowPilotClient:
    """Talks to ShowPilot's viewer API (no auth) and plugin API (show token).

    Only read-only plugin calls are used for polling. In particular this never
    calls GET /api/plugin/state without peek=1: a full call hands the next
    request out to the caller, which would take it away from FPP.
    """

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str | None) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._token = token or None

    @property
    def has_token(self) -> bool:
        return self._token is not None

    def absolute(self, path: str | None) -> str | None:
        if not path:
            return None
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.url}/{path.lstrip('/')}"

    async def _request(self, method: str, path: str, *, auth: bool = False, json: Any = None) -> Any:
        headers = {}
        if auth:
            if not self._token:
                raise ShowPilotAuthError("No show token configured")
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._session.request(
                method, f"{self.url}{path}", headers=headers, json=json, timeout=TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise ShowPilotAuthError("Show token refused")
                if resp.status >= 400:
                    try:
                        body = await resp.json(content_type=None)
                        msg = body.get("error") if isinstance(body, dict) else None
                    except (aiohttp.ContentTypeError, ValueError):
                        msg = None
                    raise ShowPilotError(msg or f"HTTP {resp.status} from {path}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise ShowPilotConnectionError(f"{path}: {err}") from err

    # ---- read ----
    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def state(self) -> dict[str, Any]:
        return await self._request("GET", "/api/state")

    async def page_stats(self) -> dict[str, Any]:
        return await self._request("GET", "/api/page-stats")

    async def plugin_health(self) -> dict[str, Any]:
        return await self._request("GET", "/api/plugin/health", auth=True)

    async def plugin_peek(self) -> dict[str, Any]:
        return await self._request("GET", "/api/plugin/state?peek=1", auth=True)

    async def categories(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/plugin/categories", auth=True)
        return data.get("categories", [])

    async def viewer_pages(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/plugin/viewer-pages", auth=True)
        return data.get("pages", [])

    # ---- control ----
    async def set_mode(self, mode: str) -> dict[str, Any]:
        return await self._request("POST", "/api/plugin/viewer-mode", auth=True, json={"mode": mode})

    async def clear_queue(self) -> dict[str, Any]:
        return await self._request("POST", "/api/plugin/queue/clear", auth=True)

    async def set_category(self, name: str, enabled: bool) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/plugin/category", auth=True, json={"name": name, "enabled": enabled}
        )

    async def set_viewer_page(self, name: str) -> dict[str, Any]:
        return await self._request("POST", "/api/plugin/viewer-page", auth=True, json={"name": name})
