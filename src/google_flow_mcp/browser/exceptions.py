"""Custom exceptions for browser and automation errors."""


class BrowserException(Exception):
    """Base exception for all browser-related errors."""


class BrowserInitError(BrowserException):
    """Raised when browser fails to launch or initialize."""


class ElementNotFoundError(BrowserException):
    """Raised when an expected DOM element is not found within timeout."""


class PageTimeoutError(BrowserException):
    """Raised when a page navigation or wait operation times out."""
