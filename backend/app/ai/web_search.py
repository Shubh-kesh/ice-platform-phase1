"""
External web-search provider (W7.2) — Tavily API via a direct async httpx
wrapper (no SDK dependency: avoids pydantic/httpx version conflicts and keeps
provider code isolated). Deterministic fake testing injects a custom client
(`set_client`), so CI never touches the network.

Trust model: search results are EXTERNAL, UNTRUSTED evidence. The tool treats
them as data — never instructions — and the system prompt says so.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("ice.ai")

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class WebSearchTransientError(Exception):
    """Transient external failure (timeout / connection / 5xx / 429).

    Raised so ToolRetryMiddleware (scoped to `web_search`) can retry with
    exponential backoff. Never raised for deterministic/configuration errors.
    """


class WebSearchRejectedError(ValueError):
    """Deterministic external-search failure (malformed response / 4xx).

    NOT retryable — surfaced as a safe model-visible error dict.
    """


def on_retry_failure(exc: Exception) -> str:
    """Model-visible safe message used by ToolRetryMiddleware `on_failure`.

    Returns a JSON error dict so the SSE adapter can classify the exhausted
    failure as an error (ok=False, error=external_service_error).
    """
    logger.info("web_search retries exhausted: %s", type(exc).__name__)
    return json.dumps(
        {
            "error": "external_service_error",
            "detail": "The external search service is temporarily unavailable.",
        }
    )


class TavilyWebClient:
    """Minimal async Tavily search client (injectable for deterministic tests)."""

    def __init__(self, api_key: str | None = None, timeout_s: float | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.ICE_AI_TAVILY_API_KEY
        self.timeout_s = (
            timeout_s
            if timeout_s is not None
            else settings.ICE_AI_WEB_SEARCH_TIMEOUT_SECONDS
        )

    async def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.post(
                    TAVILY_SEARCH_URL,
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": max_results,
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise WebSearchTransientError(
                    "external search timeout or connection failure"
                ) from exc
            if response.status_code in (408, 429) or response.status_code >= 500:
                raise WebSearchTransientError(
                    f"external search service error (HTTP {response.status_code})"
                ) from None
            if response.status_code >= 400:
                raise WebSearchRejectedError(
                    "The external search request was rejected."
                ) from None
            try:
                data = response.json()
            except ValueError as exc:
                raise WebSearchRejectedError(
                    "The external search returned an unparseable response."
                ) from exc
            results = data.get("results", []) if isinstance(data, dict) else []
            if not isinstance(results, list):
                raise WebSearchRejectedError(
                    "The external search returned an unexpected response shape."
                ) from None
            return results


_client: TavilyWebClient | None = None


def get_client() -> TavilyWebClient:
    global _client
    if _client is None:
        _client = TavilyWebClient()
    return _client


def set_client(client: TavilyWebClient | None) -> None:
    """Test seam: inject a fake client so CI never touches the network."""
    global _client
    _client = client
