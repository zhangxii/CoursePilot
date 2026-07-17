"""Bounded retry helpers for idempotent external operations."""

import asyncio
from collections.abc import Awaitable, Callable


class ExternalServiceTimeout(TimeoutError):
    """Friendly terminal timeout after bounded attempts."""


async def with_retry[ResultT](
    operation: Callable[[], Awaitable[ResultT]],
    *,
    attempts: int,
    timeout_seconds: float,
) -> ResultT:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return await asyncio.wait_for(operation(), timeout_seconds)
        except (TimeoutError, ConnectionError) as error:
            last_error = error
    raise ExternalServiceTimeout(f"外部服务在 {attempts} 次尝试后仍不可用") from last_error
