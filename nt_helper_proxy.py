"""HTTP proxy client for thorinside/nt_helper MCP server.

Connects to the nt_helper Flutter app's Streamable HTTP MCP endpoint
using JSON-RPC 2.0. Provides convenience methods for the most useful tools
and graceful degradation when the app is not running.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("es-orchestrator.nt_helper_proxy")


class NTHelperProxy:
    """Async client for the nt_helper MCP server (Streamable HTTP)."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)
        self._session_id: str | None = None
        self._available: bool | None = None  # None = not yet probed
        self._request_id = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _initialize(self) -> bool:
        """Send MCP initialize + notifications/initialized handshake."""
        try:
            resp = await self._client.post(
                self._base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": await self._next_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "es-orchestrator-mcp",
                            "version": "0.1.0",
                        },
                    },
                },
            )
            resp.raise_for_status()

            # Capture session ID from response header
            session_id = resp.headers.get("mcp-session-id")
            if session_id:
                self._session_id = session_id

            # Send initialized notification (no id = notification)
            headers = {}
            if self._session_id:
                headers["mcp-session-id"] = self._session_id
            await self._client.post(
                self._base_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
                headers=headers,
            )

            self._available = True
            return True

        except (httpx.HTTPError, Exception) as e:
            logger.warning("nt_helper initialize failed: %s", e)
            self._available = False
            return False

    async def check_available(self) -> bool:
        """Check if nt_helper is reachable. Caches result after first probe."""
        if self._available is not None:
            return self._available
        return await self._initialize()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    @property
    def available(self) -> bool | None:
        """Current availability status (None if not yet probed)."""
        return self._available

    # ------------------------------------------------------------------
    # JSON-RPC transport
    # ------------------------------------------------------------------

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any | None:
        """Call a tool on the nt_helper MCP server.

        Returns the parsed result content, or None on error.
        """
        if not self._available:
            if not await self._initialize():
                return None

        headers = {}
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        try:
            resp = await self._client.post(
                self._base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": await self._next_id(),
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments or {},
                    },
                },
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                logger.warning("nt_helper tool %s error: %s", name, data["error"])
                return None

            result = data.get("result", {})
            # MCP tool results have content array
            content = result.get("content", [])
            if content and isinstance(content, list):
                # Return the text of the first content block
                first = content[0]
                if isinstance(first, dict):
                    return first.get("text", str(first))
                return str(first)
            return result

        except (httpx.HTTPError, Exception) as e:
            logger.warning("nt_helper call_tool(%s) failed: %s", name, e)
            self._available = False
            return None

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def show_routing(self) -> str | None:
        """Get the current Disting NT routing visualization."""
        return await self.call_tool("show_routing")

    async def show_screen(self, display_mode: str = "") -> str | None:
        """Get the Disting NT screen content."""
        args = {}
        if display_mode:
            args["display_mode"] = display_mode
        return await self.call_tool("show_screen", args)

    async def edit_slot(self, slot_index: int, data: dict) -> str | None:
        """Edit parameters on a specific algorithm slot."""
        return await self.call_tool("edit_slot", {
            "slot_index": slot_index,
            **data,
        })

    async def add_algorithm(
        self,
        name: str = "",
        guid: str = "",
        slot_index: int = -1,
    ) -> str | None:
        """Add an algorithm by name or GUID."""
        args: dict[str, Any] = {}
        if name:
            args["name"] = name
        if guid:
            args["guid"] = guid
        if slot_index >= 0:
            args["slot_index"] = slot_index
        return await self.call_tool("add", args)

    async def search_parameters(
        self,
        query: str,
        scope: str = "preset",
        slot_index: int = -1,
        partial_match: bool = False,
    ) -> str | None:
        """Search parameters across the current preset or a specific slot."""
        args: dict[str, Any] = {"query": query, "scope": scope}
        if slot_index >= 0:
            args["slot_index"] = slot_index
        if partial_match:
            args["partial_match"] = True
        return await self.call_tool("search_parameters", args)
