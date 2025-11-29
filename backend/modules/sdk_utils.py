from typing import Any
import asyncio
import inspect
import logging

logger = logging.getLogger("UFC_AGENT")


def await_if_needed(obj: Any) -> Any:
    """Await the given object if it's awaitable; otherwise return it as-is.
    Works as a synchronous helper (uses run_until_complete or asyncio.run as fallback).
    """
    if inspect.isawaitable(obj):
        try:
            return asyncio.get_event_loop().run_until_complete(obj)
        except RuntimeError:

            async def _await_coro(r):
                return await r

            return asyncio.run(_await_coro(obj))
    return obj
