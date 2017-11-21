import asyncio
import functools


def with_timeout(timeout=1.0):
    def decorator(coro):
        @functools.wraps(coro)
        async def wrapper(self, *args, **kwargs):
            return (await asyncio.wait_for(coro(self, *args, **kwargs), timeout=timeout))

        return wrapper
    return decorator
