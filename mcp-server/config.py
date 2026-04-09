"""MCP server configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """MCP server settings loaded from environment variables."""

    # Backend API base URL
    backend_url: str = "http://localhost:8080"

    # API key for authenticating against the backend
    api_key: str = ""

    # MCP server settings
    mcp_host: str = "0.0.0.0"  # noqa: S104 — used only for streamable-http transport, not in stdio mode
    mcp_port: int = 8081

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
