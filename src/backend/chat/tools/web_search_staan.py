"""Web search tool using Staan (European Search Perspective) for the chat agent.

Staan is the EU-sovereign search API built on the independent European index of
the Ecosia × Qwant joint venture. Data stays under EU jurisdiction, which is why
this backend exists next to the Brave (US) one.

API: GET https://api.staan.ai/v2/search/web — Bearer auth, `extra_snippets`
returns scored content chunks per result, ready for context injection.
See https://docs.staan.ai
"""

import logging
from typing import List

from django.conf import settings

import httpx
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolReturn

from chat.tools.exceptions import ModelCannotRetry
from chat.tools.utils import last_model_retry_soft_fail
from chat.tools.web_search_brave import format_tool_return

logger = logging.getLogger(__name__)

STAAN_WEB_SEARCH_URL = "https://api.staan.ai/v2/search/web"


def _normalize_staan_results(json_response: dict) -> List[dict]:
    """Normalize Staan results to the common web search schema.

    Staan returns per result: title, url, snippet and (with enrichment)
    `extra_snippets` as `{chunk, score}` objects sorted by descending score.
    We flatten those chunks into the plain-string `snippets` list that
    `format_tool_return` expects, keeping the plain snippet as a fallback.
    """
    normalized = []
    for result in json_response.get("web", {}).get("results", []):
        chunks = [
            chunk["chunk"]
            for chunk in result.get("extra_snippets") or []
            if chunk.get("chunk")
        ]
        snippets = chunks or ([result["snippet"]] if result.get("snippet") else [])
        normalized.append(
            {
                "url": result.get("url"),
                "title": result.get("title"),
                "snippets": snippets,
            }
        )
    return normalized


async def _query_staan_api_async(query: str) -> List[dict]:
    """Query the Staan web search endpoint and return normalized results."""
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.STAAN_API_KEY}",
    }
    params = {
        "q": query,
        "market": settings.STAAN_SEARCH_MARKET,
        "extra_snippets": "true",
        "max_snippets": settings.STAAN_MAX_SNIPPETS,
        "min_score": settings.STAAN_MIN_SCORE,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.STAAN_API_TIMEOUT) as client:
            response = await client.get(STAAN_WEB_SEARCH_URL, headers=headers, params=params)
            response.raise_for_status()
            return _normalize_staan_results(response.json())

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            logger.warning("Staan API rate limited: %s", e)
            raise ModelRetry(
                "The search API is rate limited. Please wait a moment and try again."
            ) from e
        if e.response.status_code >= 500:
            logger.warning("Staan API error: %s", e)
            raise ModelRetry(
                "The search service is temporarily unavailable due to a server error. Retrying..."
            ) from e

        logger.error("Staan API client error: %s", e)
        raise ModelCannotRetry(
            f"Web search failed with a client error (status {e.response.status_code}). "
            "You must explain this to the user and not try to answer based on your knowledge."
        ) from e
    except httpx.TimeoutException as e:
        logger.warning("Staan API timeout: %s", e)
        raise ModelRetry("The search request timed out. Retrying with a fresh attempt...") from e
    except httpx.HTTPError as e:
        logger.warning("Staan API connection error: %s", e)
        raise ModelRetry(
            f"Connection error while searching the web: {type(e).__name__}. Retrying..."
        ) from e
    except Exception as e:
        logger.exception("Unexpected error querying Staan API: %s", e)
        raise ModelCannotRetry(
            f"An unexpected error occurred with the search service: {type(e).__name__}. "
            "You must explain this to the user and not try to answer based on your knowledge."
        ) from e


@last_model_retry_soft_fail
async def web_search_staan(_ctx: RunContext, query: str) -> ToolReturn:
    """
    Search the web for up-to-date information.
    This function uses the Staan (European Search Perspective) web search API.
    """
    raw_search_results = await _query_staan_api_async(query)
    return format_tool_return(raw_search_results)
