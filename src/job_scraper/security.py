"""API-key roles and bounded, per-process sliding-window request limits."""

import hmac
import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from starlette.responses import JSONResponse


def key_role(key, settings):
    if key is None:
        return None
    supplied = key.encode()
    if hmac.compare_digest(supplied, settings.admin_key.encode()):
        return "admin"
    if hmac.compare_digest(supplied, settings.api_key.encode()):
        return "read"
    return None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_after: int

    def headers(self):
        result = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(math.ceil(time.time() + self.reset_after)),
        }
        if not self.allowed:
            result["Retry-After"] = str(self.reset_after)
        return result


class RateLimiter:
    def __init__(self, *, max_clients=4096, clock=time.monotonic):
        self.max_clients, self.clock = max_clients, clock
        self.buckets = OrderedDict()
        self.lock = threading.Lock()

    def consume(self, identity, limit):
        with self.lock:
            current = self.clock()
            cutoff = current - 60
            # Ordered by last activity; remove expired identities without scanning all clients.
            while self.buckets and next(iter(self.buckets.values()))[-1] <= cutoff:
                self.buckets.popitem(last=False)
            bucket = self.buckets.get(identity)
            if bucket is None:
                if len(self.buckets) >= self.max_clients:
                    return Decision(False, limit, 0, 60)
                bucket = self.buckets[identity] = deque()
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return Decision(False, limit, 0, max(1, math.ceil(bucket[0] + 60 - current)))
            bucket.append(current)
            self.buckets.move_to_end(identity)
            return Decision(
                True, limit, limit - len(bucket), max(1, math.ceil(bucket[0] + 60 - current))
            )


class RateLimitMiddleware:
    def __init__(self, app, state):
        self.app, self.state = app, state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/healthz":
            return await self.app(scope, receive, send)
        settings, limiter = self.state.settings, self.state.limiter
        # Use the same first header as Starlette/FastAPI, including for duplicate headers.
        raw = next(
            (value for name, value in scope.get("headers", []) if name.lower() == b"x-api-key"),
            None,
        )
        role = key_role(raw.decode("latin-1") if raw is not None else None, settings)
        # ASGI's client is set by the server's trusted-proxy handling. Never trust raw XFF here.
        address = scope.get("client")
        address = address[0] if address else "unknown"
        checks = [(f"ip:{address}", settings.ip_rate_limit_per_minute)]
        if role:
            checks.append((f"key:{role}", settings.api_rate_limit_per_minute))
            if role == "admin" and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                checks.append(("admin:write", settings.admin_rate_limit_per_minute))
        else:
            # Arbitrary attacker-supplied keys never become bucket identifiers.
            checks.append((f"invalid:{address}", settings.auth_rate_limit_per_minute))
        decisions = []
        for identity, limit in checks:
            decision = limiter.consume(identity, limit)
            if not decision.allowed:
                response = JSONResponse(
                    {"detail": "API request rate limit exceeded"},
                    status_code=429,
                    headers=decision.headers(),
                )
                return await response(scope, receive, send)
            decisions.append(decision)
        limiting = min(decisions, key=lambda decision: decision.remaining)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        *(
                            (key.lower().encode(), value.encode())
                            for key, value in limiting.headers().items()
                        ),
                    ],
                }
            await send(message)

        return await self.app(scope, receive, send_with_headers)
