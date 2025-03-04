"""Strictly utility functions."""

import asyncio
import re
import unicodedata
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar


# TODO: there's a `slugify` pkg, consider using that instead
def slugify(s: str) -> str:
    """Slugify a string, removes unicode.

    Based on `django.utils.text.slugify()`.
    """
    fn = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    fn = re.sub(r"[^\w\s-]", "", fn.lower())
    fn = re.sub(r"[-\s]+", "-", fn)
    return fn.strip("-_")


T = TypeVar("T")


def run_async_in_thread(async_func: Coroutine[None, None, T]) -> T:
    """Useful to lazily run async functions in a sync function running in an async context.

    Runs in a new thread, it's the lazy approach. It circumvents not being able to use
    `asyncio.run()` because there is already an event loop running.
    """

    def run(loop: asyncio.AbstractEventLoop) -> T:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(async_func)

    loop = asyncio.new_event_loop()
    with ThreadPoolExecutor() as executor:
        future = executor.submit(run, loop)
        return future.result()


__all__ = ["run_async_in_thread", "slugify"]
