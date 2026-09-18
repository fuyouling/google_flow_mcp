from dataclasses import dataclass
from pathlib import Path
import yaml
from loguru import logger


@dataclass
class BrowserFlagEntry:
    enabled: bool
    flag: str
    description: str = ""


def load_browser_flags(config_path: str) -> list[str]:
    """Load browser launch flags from YAML configuration file.

    Returns only flags where enabled is True.
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
                flags.append(item.flag)
                logger.debug(f"Browser flag enabled: {item.flag} ({item.description})")
            else:
                logger.debug(f"Browser flag disabled: {item.flag}")
        except Exception as err:
            logger.warning(f"Skipping invalid browser flag entry {entry}: {err}")

    return flags
