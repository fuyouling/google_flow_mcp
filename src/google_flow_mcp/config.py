import os
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment and .env file."""

    # ── Chrome user data directory ──────────────────────────
    chrome_user_data_dir: str = "/home/ubuntu/google_flow_mcp/chrome_data"
    chrome_profile_directory: str = "Default"

    # Chrome binary path (empty = DrissionPage automatic detection)
    chrome_binary_path: str = ""

    # Chrome default download directory (empty = system default)
    chrome_download_dir: str = ""

    # Browser flags YAML config path
    browser_config_path: str = str(PROJECT_ROOT / "browser_config.yaml")

    # Proxy settings
    proxy_server: str = ""

    # Google Flow URLs and Logging
    google_flow_base_url: str = "https://flow.google.com"
    log_level: str = "INFO"

    # Cluster settings
    cluster_master_host: str = "0.0.0.0"
    cluster_master_port: int = 8765
    cluster_grpc_port: int = 50051
    cluster_master_url: str = "http://127.0.0.1:8765"
    cluster_grpc_target: str = "127.0.0.1:50051"
    cluster_asset_dir: str = str(PROJECT_ROOT / "data" / "assets")
    worker_id: str = "master_local_worker"
    worker_account: str = ""
    is_cluster_enabled: bool = True
    auto_launch_browser: bool = False

    @field_validator("chrome_user_data_dir", mode="before")
    @classmethod
    def normalize_path(cls, v: str) -> str:
        """Normalize user data path to platform canonical absolute path."""
        if not v:
            return v
        return str(Path(v).expanduser().resolve())

    @field_validator("chrome_download_dir", mode="before")
    @classmethod
    def normalize_download_dir(cls, v: str) -> str:
        """Normalize download directory path."""
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
        env_file=(str(PROJECT_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get singleton Settings instance and synchronize to os.environ."""
    global _settings
    if _settings is None:
        _settings = Settings()
        if _settings.chrome_download_dir:
            os.environ.setdefault("CHROME_DOWNLOAD_DIR", _settings.chrome_download_dir)
        if _settings.chrome_user_data_dir:
            os.environ.setdefault("CHROME_USER_DATA_DIR", _settings.chrome_user_data_dir)
    return _settings


def reset_settings() -> None:
    """Reset cached settings, mainly for testing."""
    global _settings
    _settings = None

