import sys
from pathlib import Path
from DrissionPage import ChromiumOptions, Chromium
from loguru import logger

from google_flow_mcp.browser.exceptions import BrowserInitError
from google_flow_mcp.browser.launcher import load_browser_flags, get_browser_port
from google_flow_mcp.config import get_settings

_page: Chromium | None = None


def _configure_logging(log_level: str = "INFO") -> None:
    """Ensure logging is directed to stderr to preserve MCP stdio integrity."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )


def _build_options(settings) -> ChromiumOptions:
    """Build ChromiumOptions from settings and YAML configuration."""
    options = ChromiumOptions()
    port = get_browser_port()
    options.set_local_port(port)

    # User data directory (normalized in config.py)
    if settings.chrome_user_data_dir:
        options.set_user_data_path(settings.chrome_user_data_dir)
    if settings.chrome_profile_directory:
        options.set_argument(f"--profile-directory={settings.chrome_profile_directory}")

    # Chrome default download directory
    if settings.chrome_download_dir:
        download_path = Path(settings.chrome_download_dir)
        download_path.mkdir(parents=True, exist_ok=True)
        options.set_download_path(str(download_path))
        options.set_argument("--default-download-directory", str(download_path))
        options.set_pref("download.default_directory", str(download_path))
        options.set_pref("savefile.default_directory", str(download_path))
        options.set_pref("download.prompt_for_download", False)
        logger.info(f"Browser download directory configured: {download_path}")

    # Chrome binary path (optional, empty = auto-detect by DrissionPage)
    if settings.chrome_binary_path:
        binary = Path(settings.chrome_binary_path)
        logger.info(f"Using custom Chrome path: {binary}")
        options.set_browser_path(str(binary))
    else:
        logger.info("Chrome path not specified; DrissionPage auto-detection will be used")

    if settings.proxy_server:
        logger.info(f"Configuring proxy server via DrissionPage API: {settings.proxy_server}")
        options.set_proxy(settings.proxy_server)

    # Load flags from YAML
    env_vars = {
        "CHROME_DOWNLOAD_DIR": settings.chrome_download_dir,
        "CHROME_USER_DATA_DIR": settings.chrome_user_data_dir,
        "CHROME_PROFILE_DIRECTORY": settings.chrome_profile_directory,
    }
    flags = load_browser_flags(settings.browser_config_path, env_vars=env_vars)
    for flag in flags:
        options.set_argument(flag)
        if flag.startswith("--headless"):
            options.headless()
    logger.info(f"Loaded {len(flags)} browser startup flags")

    return options


def get_browser() -> Chromium:
    """Get or initialize the global singleton Chromium instance."""
    global _page
    
    if _page is not None:
        try:
            # Check if browser is still responsive
            _ = _page.version
        except Exception as e:
            logger.warning(f"Existing browser instance disconnected ({e}). Re-initializing...")
            _page = None

    if _page is None:
        settings = get_settings()
        _configure_logging(settings.log_level)
        logger.info(f"Initializing browser | Platform: {sys.platform} | Profile: {settings.chrome_user_data_dir}")
        
        for attempt in range(2):
            try:
                options = _build_options(settings)
                
                import os
                os.environ["DISPLAY"] = ":0"  # 硬编码注入图形环境变量，供本地调试期间在 MCP 内唤起界面使用
                    
                _page = Chromium(addr_or_opts=options)
                logger.info("Browser instance ready")
                break
            except Exception as e:
                import traceback
                import os
                
                if "BrowserConnectError" in str(e):
                    port = get_browser_port()
                    logger.warning(f"BrowserConnectError detected. Attempting to clean up zombie processes and locks on port {port} before retry...")
                    try:
                        from google_flow_mcp.browser.utils import stop_browser
                        stop_browser(port)
                    except Exception as e_clean:
                        logger.warning(f"Failed to clean port {port}: {e_clean}")
                        
                    if settings.chrome_user_data_dir:
                        lock_file = os.path.join(settings.chrome_user_data_dir, "SingletonLock")
                        if os.path.exists(lock_file):
                            try:
                                os.remove(lock_file)
                                logger.info(f"Removed stale SingletonLock at {lock_file}")
                            except Exception as e2:
                                logger.error(f"Failed to remove SingletonLock: {e2}")
                    
                    import time
                    time.sleep(1)
                    continue
                
                from google_flow_mcp.config import PROJECT_ROOT
                err_log_path = PROJECT_ROOT / "mcp_error.log"
                with open(err_log_path, "w", encoding="utf-8") as f:
                    f.write(f"Exception Type: {type(e).__name__}\n")
                    f.write(f"Exception Message: {str(e)}\n")
                    f.write("Traceback:\n")
                    f.write(traceback.format_exc())
                
                logger.error(f"Failed to initialize browser: {e}")
                raise BrowserInitError(f"Failed to launch browser: {e}") from e
    return _page


def set_browser(browser: Chromium | None) -> None:
    """Set global browser instance (useful for testing or mocking)."""
    global _page
    _page = browser


def close_browser(force: bool = False) -> None:
    """Close and release the global browser instance.
    
    If the browser instance was connected to an already running external browser
    (_is_exists=True) and force is False, the browser process will NOT be terminated,
    only the local session reference will be released.
    """
    global _page
    if _page:
        is_external = getattr(_page, "_is_exists", False)
        if is_external and not force:
            logger.info("External persistent browser instance detected (_is_exists=True). Preserving browser process and releasing session reference.")
            _page = None
            return

        logger.info("Closing browser...")
        try:
            _page.quit()
        except Exception as e:
            logger.warning(f"Error while quitting browser: {e}")
        finally:
            _page = None
