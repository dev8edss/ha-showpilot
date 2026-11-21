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


class ShowPilotAdmin:
    """ShowPilot admin login, used only to read visitor messages.

    Only the admin API can read messages (the show token can't). The session
    cookie is kept here and sent by hand: aiohttp's cookie jar ignores cookies
    from bare IP addresses, which is how most people reach ShowPilot.
    """

    COOKIE = "showpilot_session"

    def __init__(self, session: aiohttp.ClientSession, url: str, username: str, password: str) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._username = username
        self._password = password
        self._cookie: str | None = None
        self._cookie_name = self.COOKIE

    async def login(self) -> None:
        try:
            async with self._session.post(
                f"{self.url}/api/admin/login",
                json={"username": self._username, "password": self._password},
                timeout=TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise ShowPilotAuthError("ShowPilot refused that user name or password")
                if resp.status == 429:
                    raise ShowPilotError("Too many ShowPilot logins; try again in a few minutes")
                if resp.status >= 400:
                    raise ShowPilotError(f"HTTP {resp.status} from login")
                # The cookie name is configurable on the server; take the default
                # one, or the only cookie the login set.
                name = self._cookie_name
                if name not in resp.cookies and len(resp.cookies) == 1:
                    name = next(iter(resp.cookies))
                morsel = resp.cookies.get(name)
                if morsel is None or not morsel.value:
                    raise ShowPilotError("ShowPilot didn't return a session")
                self._cookie_name = name
                self._cookie = morsel.value
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ShowPilotConnectionError(f"login: {err}") from err

    async def _get(self, path: str) -> Any:
        for attempt in (1, 2):
            if self._cookie is None:
                await self.login()
            try:
                async with self._session.get(
                    f"{self.url}{path}", headers={"Cookie": f"{self._cookie_name}={self._cookie}"}, timeout=TIMEOUT
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        self._cookie = None  # session expired: log in again once
                        continue
                    if resp.status == 401:
                        raise ShowPilotAuthError("ShowPilot login no longer accepted")
                    if resp.status >= 400:
                        raise ShowPilotError(f"HTTP {resp.status} from {path}")
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                raise ShowPilotConnectionError(f"{path}: {err}") from err
        raise ShowPilotAuthError("ShowPilot login no longer accepted")

    async def messages(self, limit: int = 20) -> dict[str, Any]:
        """Newest first: {messages: [{id, created_at, name, message, filtered, is_read, allow_public, is_public}], unread}."""
        return await self._get(f"/api/admin/messages?filter=all&limit={limit}")
