import asyncio
import time
from collections import deque


MAX_REQUESTS = 10
WINDOW_SECONDS = 60


class RateLimiter:

    def __init__(
        self,
        max_requests: int = MAX_REQUESTS,
        window_seconds: int = WINDOW_SECONDS
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

        self.request_times = deque()
        self.lock = asyncio.Lock()

    async def acquire(self):
        while True:

            async with self.lock:

                now = time.monotonic()

                # Remove requests that are older than
                # our rolling window.
                while (
                    self.request_times
                    and now - self.request_times[0]
                    >= self.window_seconds
                ):
                    self.request_times.popleft()

                # We can make a request immediately.
                if len(self.request_times) < self.max_requests:

                    self.request_times.append(now)

                    return

                # The oldest request determines when
                # the next slot becomes available.
                wait_time = (
                    self.window_seconds
                    - (now - self.request_times[0])
                )

            print(
                f"Rate limit reached. "
                f"Waiting {wait_time:.2f}s."
            )

            await asyncio.sleep(wait_time)


rate_limiter = RateLimiter()