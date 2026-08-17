"""Retry with exponential backoff + jitter."""
from __future__ import annotations
import random, time, functools, logging
from typing import Callable, Any
log = logging.getLogger("parser_v2.retry")

def retry(max_attempts: int = 3, base_delay: float = 2.0, exceptions: tuple = (Exception,)):
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try: return fn(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                        log.warning("Retry %d/%d %s: %s (%.1fs)", attempt, max_attempts, fn.__name__, e, delay)
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
