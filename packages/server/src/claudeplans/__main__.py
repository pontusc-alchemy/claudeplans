"""uvicorn entrypoint that drains SSE streams before the graceful-shutdown wait.

On SIGTERM uvicorn sets keep_alive=False, then waits out --timeout-graceful-shutdown,
then CANCELS any still-open SSE task, and ONLY THEN runs the ASGI lifespan shutdown.
So closing the feed in the lifespan `finally` fires too late: open SSE generators get
force-cancelled at the timeout instead of draining via the sentinel. This Server
subclass closes the feed at the START of uvicorn's shutdown, so the sentinel reaches
every open generator and they complete during the graceful wait. The container's
ENTRYPOINT is `python -m claudeplans` so this subclass is what runs in production.
"""

import socket

import uvicorn

from .main import app


class _Server(uvicorn.Server):
    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        # Close the change feed FIRST: the sentinel reaches open SSE generators so
        # they complete during uvicorn's graceful wait, instead of being force-
        # cancelled at the --timeout-graceful-shutdown deadline (uvicorn runs the
        # ASGI lifespan shutdown only AFTER that wait, which is too late).
        feed = getattr(app.state, "feed", None)
        if feed is not None:
            feed.close()
        await super().shutdown(sockets)


def main() -> None:
    config = uvicorn.Config(
        "claudeplans.main:app",
        host="0.0.0.0",
        port=8000,
        timeout_graceful_shutdown=10,
    )
    _Server(config).run()


if __name__ == "__main__":
    main()
