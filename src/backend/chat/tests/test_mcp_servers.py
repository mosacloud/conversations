"""Tests for the configuration-driven MCP servers loader (chat.mcp_servers)."""

import json

from django.test import override_settings

import pytest
from pydantic_ai.mcp import MCPServerSSE, MCPServerStreamableHTTP

from chat.mcp_servers import (
    _resolve_env,
    get_mcp_servers,
    load_mcp_servers_configuration,
)


@override_settings(MCP_SERVERS_CONFIGURATION=None, MCP_SERVERS_CONFIGURATION_FILE_PATH=None)
def test_no_configuration_returns_no_servers():
    """With nothing configured, no MCP servers are attached (upstream default)."""
    assert load_mcp_servers_configuration() == {"mcpServers": {}}
    assert get_mcp_servers() == []


@override_settings(
    MCP_SERVERS_CONFIGURATION=json.dumps(
        {
            "mcpServers": {
                "kb": {"url": "https://example.org/mcp", "transport": "streamable-http"},
                "legacy": {"url": "https://legacy.example.org/mcp", "transport": "sse"},
            }
        }
    ),
    MCP_SERVERS_CONFIGURATION_FILE_PATH=None,
)
def test_inline_json_builds_servers_with_selected_transport():
    servers = get_mcp_servers()
    assert len(servers) == 2
    assert isinstance(servers[0], MCPServerStreamableHTTP)
    assert isinstance(servers[1], MCPServerSSE)


@override_settings(MCP_SERVERS_CONFIGURATION=None, MCP_SERVERS_CONFIGURATION_FILE_PATH=None)
def test_transport_defaults_to_streamable_http():
    with override_settings(
        MCP_SERVERS_CONFIGURATION=json.dumps(
            {"mcpServers": {"kb": {"url": "https://example.org/mcp"}}}
        )
    ):
        servers = get_mcp_servers()
    assert len(servers) == 1
    assert isinstance(servers[0], MCPServerStreamableHTTP)


def test_file_path_takes_precedence_over_inline(tmp_path):
    config_file = tmp_path / "mcp.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"from_file": {"url": "https://file.example.org/mcp"}}})
    )
    with override_settings(
        MCP_SERVERS_CONFIGURATION=json.dumps(
            {"mcpServers": {"from_inline": {"url": "https://inline.example.org/mcp"}}}
        ),
        MCP_SERVERS_CONFIGURATION_FILE_PATH=str(config_file),
    ):
        config = load_mcp_servers_configuration()
    assert list(config["mcpServers"]) == ["from_file"]


def test_header_env_placeholders_are_resolved(monkeypatch):
    monkeypatch.setenv("MY_MCP_TOKEN", "s3cret")
    assert _resolve_env("Bearer ${MY_MCP_TOKEN}") == "Bearer s3cret"
    # Unknown placeholders resolve to empty rather than leaking the literal.
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    assert _resolve_env("Bearer ${MISSING_TOKEN}") == "Bearer "


@override_settings(
    MCP_SERVERS_CONFIGURATION=json.dumps(
        {"mcpServers": {"bad": {"url": "https://example.org/mcp", "transport": "carrier-pigeon"}}}
    ),
    MCP_SERVERS_CONFIGURATION_FILE_PATH=None,
)
def test_unknown_transport_raises():
    with pytest.raises(ValueError, match="unsupported transport"):
        get_mcp_servers()
