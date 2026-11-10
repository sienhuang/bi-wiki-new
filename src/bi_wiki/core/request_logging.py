"""Pure ASGI middleware: include streaming completion and always release context."""

from time import perf_counter
from uuid import uuid4

from bi_wiki.core.logging import log_context, logger


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status = 500
        outcome = "failed"

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ] + [(b"x-request-id", request_id.encode())]
            await send(message)

        with log_context(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
                outcome = "completed"
            finally:
                route = scope.get("route")
                logger.info(
                    "http_request",
                    extra={
                        "method": scope["method"],
                        "route": getattr(route, "path", "<unmatched>"),
                        "status_code": status,
                        "status": outcome,
                        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                    },
                )
