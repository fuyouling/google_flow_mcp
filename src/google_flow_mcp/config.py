from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and .env file."""

    # ── Chrome user data directory ──────────────────────────
    chrome_user_data_dir: str = "/home/ubuntu/google_flow_mcp/chrome_data"
    chrome_profile_directory: str = "Default"

    # Chrome binary path (empty = DrissionPage automatic detection)
    chrome_binary_path: str = ""

    # Browser flags YAML config path
    browser_config_path: str = "browser_config.yaml"

    # Proxy settings
    proxy_server: str = ""

    # Google Flow URLs and Logging
    google_flow_base_url: str = "https://flow.google.com"
    log_level: str = "INFO"

    @field_validator("chrome_user_data_dir", mode="before")
    @classmethod
    def normalize_path(cls, v: str) -> str:
        """Normalize user data path to platform canonical absolute path."""
        if not v:
            return v
        return str(Path(v).expanduser().resolve())

    @field_validator("browser_config_path", mode="before")
    @classmethod
    def normalize_config_path(cls, v: str) -> str:
        """Normalize config path."""
        if not v:
            return v
        return str(Path(v).expanduser().resolve())

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get singleton Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset cached settings, mainly for testing."""
    global _settings
    _settings = None
