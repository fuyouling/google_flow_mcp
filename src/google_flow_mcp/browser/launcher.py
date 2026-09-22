import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import yaml
from loguru import logger


@dataclass
class BrowserFlagEntry:
    enabled: bool
    flag: str
    description: str = ""


def _expand_env_vars(text: str, env_vars: Mapping[str, str] | None = None) -> str:
    """Expand environment variables in text supporting ${VAR} and $VAR formats."""
    merged = dict(os.environ)
    if env_vars:
        for k, v in env_vars.items():
            if v is not None:
                merged[k] = str(v)

    def _sub(m: re.Match) -> str:
        var_name = m.group(1) or m.group(2)
        return merged.get(var_name, m.group(0))

    return re.sub(r"\$\{([A-Za-z0-9_]+)\}|\$([A-Za-z0-9_]+)", _sub, text)


def load_browser_flags(
    config_path: str, env_vars: Mapping[str, str] | None = None
) -> list[str]:
    """Load browser launch flags from YAML configuration file.

    Returns only flags where enabled is True.
    Supports environment variable substitution (e.g. ${CHROME_DOWNLOAD_DIR}).
    """
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"browser_config.yaml does not exist: {path}, fallback to empty flags")
        return []

    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to parse browser configuration {path}: {e}")
        return []

    if not data or not isinstance(data, dict):
        return []

    flags: list[str] = []
    for entry in data.get("browser", []):
        try:
            item = BrowserFlagEntry(**entry)
            if item.enabled:
                flag = _expand_env_vars(item.flag, env_vars)
                # Skip if a variable placeholder evaluated to empty value
                if flag.startswith("--default-download-directory=") and flag.split("=", 1)[1].strip() in ("", "''", '""'):
                    logger.debug(f"Skipping empty download flag: {item.flag}")
                    continue
                flags.append(flag)
                logger.debug(f"Browser flag enabled: {flag} ({item.description})")
            else:
                logger.debug(f"Browser flag disabled: {item.flag}")
        except Exception as err:
            logger.warning(f"Skipping invalid browser flag entry {entry}: {err}")

    return flags


def get_browser_port(config_path: str | None = None) -> int:
    """Extract the remote debugging port from the browser_config.yaml file.
    
    Returns 9222 as a fallback if the flag is missing or not enabled.
    """
    if config_path is None:
        from google_flow_mcp.config import get_settings
        config_path = get_settings().browser_config_path

    path = Path(config_path)
    if not path.exists():
        return 9222

    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to parse browser configuration {path}: {e}")
        return 9222

    if not data or not isinstance(data, dict):
        return 9222

    for entry in data.get("browser", []):
        try:
            item = BrowserFlagEntry(**entry)
            if item.enabled and item.flag.startswith("--remote-debugging-port="):
                port_str = item.flag.split("=", 1)[1]
                return int(port_str)
        except Exception:
            pass

    return 9222
