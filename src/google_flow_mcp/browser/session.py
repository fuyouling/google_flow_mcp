import sys
from pathlib import Path
from DrissionPage import ChromiumOptions, Chromium
from loguru import logger

from google_flow_mcp.browser.exceptions import BrowserInitError
from google_flow_mcp.browser.launcher import load_browser_flags
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
    options.set_local_port(9222)

    # User data directory (normalized in config.py)
    if settings.chrome_user_data_dir:
        options.set_user_data_path(settings.chrome_user_data_dir)
    if settings.chrome_profile_directory:
        options.set_argument(f"--profile-directory={settings.chrome_profile_directory}")

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
    flags = load_browser_flags(settings.browser_config_path)
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
            _ = _page.browser.version
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
                import subprocess
                
                is_connect_error = type(e).__name__ == "BrowserConnectError"
                
                if attempt == 0 and is_connect_error:
                    logger.warning("BrowserConnectError detected. Attempting to clean up zombie processes and locks on port 9222 before retry...")
                    try:
                        subprocess.run(["fuser", "-k", "9222/tcp"], capture_output=True)
                    except Exception:
                        pass
                        
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
                
                with open("/home/ubuntu/google_flow_mcp/scratch/mcp_error.log", "w") as f:
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


def close_browser() -> None:
    """Close and release the global browser instance."""
    global _page
    if _page:
        logger.info("Closing browser...")
        try:
            _page.quit()
        except Exception as e:
            logger.warning(f"Error while quitting browser: {e}")
        finally:
            _page = None
