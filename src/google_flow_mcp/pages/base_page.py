from typing import Any, Union
from DrissionPage import ChromiumPage
from DrissionPage.items import ChromiumTab, MixTab
from loguru import logger

from google_flow_mcp.browser.exceptions import ElementNotFoundError, PageTimeoutError


class BasePage:
    """Base page object encapsulating common browser actions and robust element handling."""

    def __init__(self, tab: Union[ChromiumTab, MixTab, ChromiumPage]):
        self.tab = tab

    def navigate(self, url: str) -> None:
        """Navigate to a specified URL."""
        logger.info(f"Navigating to URL: {url}")
        
        try:
            if hasattr(self.tab, "set") and hasattr(self.tab.set, "load_mode"):
                self.tab.set.load_mode.eager()
        except Exception as e:
            logger.debug(f"Could not set eager load mode: {e}")
            
        try:
            # Pass show_errmsg=True so DrissionPage raises exceptions on failure instead of silently returning False
            success = self.tab.get(url, show_errmsg=True, retry=2)
            if success is False:
                logger.error(f"DrissionPage tab.get returned False for {url}")
                raise PageTimeoutError(f"Navigation to {url} failed or timed out")
        except Exception as e:
            logger.error(f"Failed navigating to {url}: {e}")
            raise PageTimeoutError(f"Navigation to {url} failed: {e}") from e

    def wait_for_element(self, selector: str, timeout: float = 10.0) -> Any:
        """Wait for an element to appear in DOM and be accessible.

        Raises ElementNotFoundError if not found within timeout.
        """
        logger.debug(f"Waiting for element: '{selector}' (timeout={timeout}s)")
        
        try:
            # In DrissionPage 4.x, ele() naturally waits for the element up to the timeout.
            # If not found, it returns a NoneElement object, which is falsy.
            ele = self.tab.ele(selector, timeout=timeout)
            if ele:
                return ele
        except Exception as e:
            logger.warning(f"Error querying element '{selector}': {e}")

        raise ElementNotFoundError(f"Element '{selector}' not found within {timeout} seconds")

    def click_element(self, selector: str, timeout: float = 10.0) -> None:
        """Wait for an element and click it."""
        ele = self.wait_for_element(selector, timeout=timeout)
        try:
            ele.click()
            logger.debug(f"Clicked element: '{selector}'")
        except Exception as e:
            logger.error(f"Failed clicking element '{selector}': {e}")
            raise

    def input_text(self, selector: str, text: str, timeout: float = 10.0, clear: bool = True) -> None:
        """Input text into an element, optionally clearing it first."""
        ele = self.wait_for_element(selector, timeout=timeout)
        try:
            if clear and hasattr(ele, "clear"):
                ele.clear()
            ele.input(text)
            logger.debug(f"Entered text into '{selector}'")
        except Exception as e:
            logger.error(f"Failed inputting text into '{selector}': {e}")
            raise

    def screenshot(self) -> bytes:
        """Capture screenshot of the current page as bytes."""
        try:
            return self.tab.get_screenshot(as_bytes="png")
        except Exception as e:
            logger.warning(f"Failed to capture screenshot: {e}")
            return b""

    @property
    def current_url(self) -> str:
        """Get current URL."""
        return getattr(self.tab, "url", "")

    @property
    def title(self) -> str:
        """Get page title."""
        return getattr(self.tab, "title", "")
        
    @property
    def html(self) -> str:
        """Get page HTML."""
        return getattr(self.tab, "html", "")
