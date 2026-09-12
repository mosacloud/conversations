"""Tests for the Staan (European Search Perspective) web search tool."""

from unittest.mock import Mock

import httpx
import pytest
import respx
from pydantic_ai import RunContext, RunUsage
from pydantic_ai._run_context import RunContextAgentDepsT

from chat.tools.web_search_staan import (
    STAAN_WEB_SEARCH_URL,
    _normalize_staan_results,
    web_search_staan,
)


@pytest.fixture(autouse=True)
def staan_settings(settings):
    """Define Staan settings for tests."""
    settings.STAAN_API_KEY = "test_staan_api_key"
    settings.STAAN_API_TIMEOUT = 5
    settings.STAAN_SEARCH_MARKET = "en-us"
    settings.STAAN_MAX_SNIPPETS = 3
    settings.STAAN_MIN_SCORE = 0.1


@pytest.fixture(name="mocked_context")
def fixture_mocked_context():
    """Fixture for a mocked RunContext."""
    mock_ctx = Mock(spec=RunContext)
    mock_ctx.deps = Mock(spec=RunContextAgentDepsT)
    mock_ctx.usage = RunUsage(input_tokens=0, output_tokens=0)
    mock_ctx.max_retries = 2
    mock_ctx.retries = {}
    return mock_ctx


def test_normalize_staan_results_flattens_scored_chunks():
    """Scored chunks are flattened to plain snippets, keeping score order."""
    normalized = _normalize_staan_results(
        {
            "results": [
                {
                    "url": "https://example.eu/a",
                    "title": "Result A",
                    "snippet": "Plain snippet A",
                    "extra_snippets": [
                        {"chunk": "Chunk A1", "score": 0.9},
                        {"chunk": "Chunk A2", "score": 0.5},
                    ],
                },
                {
                    "url": "https://example.eu/b",
                    "title": "Result B",
                    "snippet": "Plain snippet B",
                },
            ]
        }
    )
    assert normalized == [
        {
            "url": "https://example.eu/a",
            "title": "Result A",
            "snippets": ["Chunk A1", "Chunk A2"],
        },
        {
            "url": "https://example.eu/b",
            "title": "Result B",
            "snippets": ["Plain snippet B"],
        },
    ]


@pytest.mark.asyncio
@respx.mock
async def test_web_search_staan_success(mocked_context):
    """A successful Staan search returns formatted results with sources."""
    route = respx.get(STAAN_WEB_SEARCH_URL).mock(
        return_value=httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "url": "https://example.eu/a",
                        "title": "Result A",
                        "snippet": "Plain snippet A",
                        "extra_snippets": [{"chunk": "Chunk A1", "score": 0.9}],
                    }
                ]
            },
        )
    )

    result = await web_search_staan(mocked_context, "test query")

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test_staan_api_key"
    assert result.return_value == {
        "0": {
            "url": "https://example.eu/a",
            "title": "Result A",
            "snippets": ["Chunk A1"],
        }
    }
    assert result.metadata == {"sources": {"https://example.eu/a"}}


@pytest.mark.asyncio
@respx.mock
async def test_web_search_staan_client_error_soft_fails(mocked_context):
    """A 4xx from Staan soft-fails: the tool returns the error message string."""
    respx.get(STAAN_WEB_SEARCH_URL).mock(return_value=httpx.Response(status_code=401))

    result = await web_search_staan(mocked_context, "test query")

    assert isinstance(result, str)
    assert "client error (status 401)" in result


@pytest.mark.asyncio
@respx.mock
async def test_web_search_staan_rate_limit_retries(mocked_context):
    """A 429 from Staan raises ModelRetry so the agent can try again."""
    respx.get(STAAN_WEB_SEARCH_URL).mock(return_value=httpx.Response(status_code=429))

    from pydantic_ai import ModelRetry  # pylint: disable=import-outside-toplevel

    with pytest.raises(ModelRetry):
        await web_search_staan(mocked_context, "test query")
