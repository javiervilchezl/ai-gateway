from collections import defaultdict, deque
from time import monotonic


class RateLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def is_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        now = monotonic()
        bucket = self._requests[key]
        cutoff = now - window_seconds

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            return True

        bucket.append(now)
        return False

    def clear(self) -> None:
        self._requests.clear()


rate_limiter = RateLimiter()
