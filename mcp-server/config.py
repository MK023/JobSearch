"""MCP server configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """MCP server settings loaded from environment variables."""

    # Backend API base URL
    backend_url: str = "http://localhost:8080"

    # API key for authenticating against the backend
    api_key: str = ""

    # MCP server settings
    # 0.0.0.0 is only bound when the server runs in streamable-http transport
    # inside a container; stdio mode (default for Claude Desktop / Claude Code)
    # never opens a listening socket.
    mcp_host: str = "0.0.0.0"  # noqa: S104
    mcp_port: int = 8081

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
