"""MCP servers configuration.

MCP (Model Context Protocol) servers are attached to the chat agent as toolsets
(see ``chat.clients.pydantic_ai``), giving the agent access to external tools and
data sources — knowledge-base search, document stores, etc. — through a single
open standard.

The set of servers is configuration, not code: it is read from settings
(``MCP_SERVERS_CONFIGURATION`` inline JSON, or ``MCP_SERVERS_CONFIGURATION_FILE_PATH``
pointing at a JSON file, e.g. a mounted ConfigMap). Secrets in headers are kept out
of the configuration document by referencing environment variables with
``${ENV_VAR}`` placeholders, resolved at load time.

Configuration shape (mirrors the common ``mcpServers`` convention)::

    {
      "mcpServers": {
        "my-kb": {
          "url": "https://example.org/mcp",
          "transport": "sse",                 # "streamable-http" (default) | "sse"
          "headers": {"Authorization": "Bearer ${MY_MCP_API_KEY}"},
          "tool_prefix": "kb"                  # optional, namespaces the server's tools
        }
      }
    }
"""

import json
import logging
import os
import re

from django.conf import settings

from pydantic_ai.mcp import MCPServerSSE, MCPServerStreamableHTTP

logger = logging.getLogger(__name__)

_ENV_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")

_TRANSPORTS = {
    "streamable-http": MCPServerStreamableHTTP,
    "http": MCPServerStreamableHTTP,
    "sse": MCPServerSSE,
}


def _resolve_env(value):
    """Replace ``${ENV_VAR}`` placeholders in a string with the environment value.

    Keeps API keys and other secrets out of the (potentially committed / ConfigMap)
    configuration document. Unknown variables resolve to an empty string.
    """
    if not isinstance(value, str):
        return value
    return _ENV_PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1), ""), value)


def load_mcp_servers_configuration() -> dict:
    """Load the raw MCP servers configuration from settings.

    ``MCP_SERVERS_CONFIGURATION_FILE_PATH`` (a JSON file) takes precedence over the
    inline ``MCP_SERVERS_CONFIGURATION`` JSON string. Returns an empty configuration
    when neither is set, so no servers are attached by default.
    """
    file_path = getattr(settings, "MCP_SERVERS_CONFIGURATION_FILE_PATH", None)
    raw = getattr(settings, "MCP_SERVERS_CONFIGURATION", None)

    if file_path:
        with open(file_path, "r", encoding="utf-8") as handle:
            raw = handle.read()

    if not raw:
        return {"mcpServers": {}}

    if isinstance(raw, (dict, list)):
        return raw

    return json.loads(raw)


def get_mcp_servers():
    """Build the list of pydantic-ai MCP server toolsets from configuration."""
    configuration = load_mcp_servers_configuration()

    servers = []
    for name, server_config in configuration.get("mcpServers", {}).items():
        config = dict(server_config)
        transport = config.pop("transport", "streamable-http")
        server_class = _TRANSPORTS.get(transport)
        if server_class is None:
            raise ValueError(
                f"MCP server '{name}': unsupported transport '{transport}'. "
                f"Expected one of {sorted(_TRANSPORTS)}."
            )

        headers = config.pop("headers", None)
        if headers:
            headers = {key: _resolve_env(val) for key, val in headers.items()}

        url = _resolve_env(config.pop("url"))

        servers.append(server_class(url=url, headers=headers, **config))

    return servers
