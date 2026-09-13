"""Custom exception classes for the SJTU Tennis Toolkit."""

from __future__ import annotations


class BookingPageNotReady(RuntimeError):
    """Raised when the browser booking page is not in the expected state."""
    pass


class RequestRateLimited(RuntimeError):
    """Raised when the school system reports daily request limit exceeded."""
    pass
