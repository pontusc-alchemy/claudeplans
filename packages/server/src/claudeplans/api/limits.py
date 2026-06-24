"""Request body-size guard.

Starlette has no built-in body limit, so a pure-ASGI middleware enforces one before
a body reaches a route: an oversized request is rejected with 413 rather than being
parsed, stored, or buffered in memory unbounded. A declared Content-Length over the
cap is rejected up front; the bytes actually received are also counted so a missing
or under-reported length (a chunked upload) cannot slip past. The byte-count check
raises HTTPException so FastAPI surfaces a clean 413 — a plain exception raised while
the request body is read gets rewrapped as a 400 by the body parser.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_TOO_LARGE = "request body too large"


class BodySizeLimitMiddleware:
    """Reject HTTP requests whose body exceeds `max_bytes` with a 413."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Fast path: a declared Content-Length over the cap is rejected before the
        # body is read at all.
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break
                if declared > self._max_bytes:
                    await self._reject(send)
                    return
                break

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    raise HTTPException(status_code=413, detail=_TOO_LARGE)
            return message

        await self._app(scope, limited_receive, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"detail":"' + _TOO_LARGE.encode() + b'"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
