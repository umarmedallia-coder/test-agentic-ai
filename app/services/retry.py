"""Shared transient-error classification for bounded agent retries."""


def is_retryable_error(error: BaseException) -> bool:
    """Retry only transport/timeouts and explicitly retryable provider failures."""
    return (
        isinstance(error, (TimeoutError, ConnectionError, OSError))
        or getattr(error, "retryable", False) is True
    )
