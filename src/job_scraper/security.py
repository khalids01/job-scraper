"""Single environment API key and an atomic Redis sliding-window quota."""

import hashlib
import hmac
import math
from dataclasses import dataclass
from uuid import uuid4

from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
from starlette.responses import JSONResponse

# Redis owns the clock and the entire check/update, so concurrent clients and app
# restarts share one accurate 60-second window. Members expire with the Redis key.
SLIDING_WINDOW = """
local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60000)
local count = redis.call('ZCARD', KEYS[1])
local allowed = 0
if count < tonumber(ARGV[1]) then
    redis.call('ZADD', KEYS[1], now, ARGV[2])
    redis.call('PEXPIRE', KEYS[1], 60000)
    count = count + 1
    allowed = 1
end
-- If MAX_REQ_PER_MIN was reduced, wait until enough older events expire.
local rank = math.max(0, count - tonumber(ARGV[1]))
local oldest = redis.call('ZRANGE', KEYS[1], rank, rank, 'WITHSCORES')
local reset = tonumber(oldest[2]) + 60000
return {allowed, count, math.max(1, reset - now), reset}
"""


def valid_key(key, settings):
    return key is not None and hmac.compare_digest(key.encode(), settings.api_key.encode())


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_at: int

    def headers(self):
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_at),
        }
        if not self.allowed:
            headers["Retry-After"] = str(self.retry_after)
        return headers


class RedisRateLimiter:
    def __init__(self, settings):
        self.limit = settings.max_req_per_min
        self.key = "job-scraper:rate:" + hashlib.sha256(settings.api_key.encode()).hexdigest()
        self.redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        )

    async def ping(self):
        await self.redis.ping()

    async def close(self):
        await self.redis.aclose()

    async def consume(self):
        allowed, count, delay, reset = await self.redis.eval(
            SLIDING_WINDOW, 1, self.key, self.limit, uuid4().hex
        )
        return Decision(
            bool(allowed),
            self.limit,
            max(0, self.limit - count),
            max(1, math.ceil(delay / 1000)),
            math.ceil(reset / 1000),
        )


class RateLimitMiddleware:
    def __init__(self, app, state):
        self.app, self.state = app, state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/healthz":
            return await self.app(scope, receive, send)
        raw = next(
            (value for name, value in scope.get("headers", []) if name.lower() == b"x-api-key"),
            None,
        )
        if not valid_key(raw.decode("latin-1") if raw is not None else None, self.state.settings):
            return await JSONResponse({"detail": "Invalid API key"}, status_code=401)(
                scope, receive, send
            )
        try:
            decision = await self.state.limiter.consume()
        except RedisError:
            # Never expose connection details or silently disable the quota on outage.
            return await JSONResponse(
                {"detail": "Rate limiter unavailable"},
                status_code=503,
                headers={"Retry-After": "2"},
            )(scope, receive, send)
        if not decision.allowed:
            return await JSONResponse(
                {"detail": "API request rate limit exceeded"},
                status_code=429,
                headers=decision.headers(),
            )(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        *(
                            (key.lower().encode(), value.encode())
                            for key, value in decision.headers().items()
                        ),
                    ],
                }
            await send(message)

        return await self.app(scope, receive, send_with_headers)
