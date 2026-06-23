"""In-process change feed — the single source of "something changed".

Subscribers: the SSE route (live view). Per-subscriber queues are BOUNDED with a
drop-OLDEST policy so one stuck reader cannot grow memory without bound. Dropping
the oldest (not the newest) is correct here: each Event triggers a full doc
re-render, so a slow reader that misses intermediate revs still converges to the
latest state. In-process => a single uvicorn worker; a shared broker for
multi-replica is deferred.

`close()` pushes a None sentinel to every subscriber so each open subscription
terminates. The __main__ Server subclass calls it at the START of uvicorn's
shutdown so the sentinel reaches open SSE generators and they complete WITHIN the
bounded graceful timeout, instead of being force-cancelled at the deadline (uvicorn
runs the ASGI lifespan shutdown only after that wait). `close()` is idempotent, so
the Server-subclass call and the lifespan `finally` backstop can both invoke it.

`subscribe()` returns a `Subscription` that registers its queue EAGERLY (in
`__init__`, synchronously), not lazily on first iteration. This closes the window
where an Event published between snapshot-render and first-iteration would be lost:
the queue exists from the moment the caller enters the `with` block.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Self


@dataclass(frozen=True, slots=True)
class Event:
    """A change notification: which document changed, and its new rev."""

    key: str
    rev: str


class Subscription(AsyncIterator[Event]):
    """A registered subscriber stream over a feed's fan-out.

    Registration is eager: the bounded queue is created and added to the feed's
    subscriber set in `__init__`, so no Event published after construction can be
    missed. Used as a sync context manager — `__exit__` unsubscribes the queue on
    disconnect or shutdown. Iteration ends on the `None` shutdown sentinel.
    """

    def __init__(self, feed: EventFeed, maxsize: int) -> None:
        self._feed = feed
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize)
        feed._subscribers.add(self._queue)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._feed._subscribers.discard(self._queue)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Event:
        event = await self._queue.get()
        if event is None:
            raise StopAsyncIteration
        return event


class EventFeed:
    """Fan-out of change Events to bounded per-subscriber queues."""

    def __init__(self, *, maxsize: int = 64) -> None:
        self._subscribers: set[asyncio.Queue[Event | None]] = set()
        self._maxsize = maxsize
        self._closed = False

    def publish(self, event: Event) -> None:
        """Offer `event` to every subscriber, dropping the oldest if a queue is full.

        Never blocks. A no-op after close so a late write can't wake a torn-down feed.
        """
        if self._closed:
            return
        for queue in self._subscribers:
            self._offer(queue, event)

    @staticmethod
    def _offer(queue: asyncio.Queue[Event | None], item: Event | None) -> None:
        """Put `item`, evicting the oldest queued item first if the queue is full."""
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            queue.get_nowait()
            queue.put_nowait(item)

    def subscribe(self) -> Subscription:
        """Return a Subscription with its queue registered EAGERLY.

        Registration happens synchronously in `Subscription.__init__`, so an Event
        published any time after this returns is queued, not lost. Use it as a
        context manager so the queue is discarded on disconnect or shutdown:
        `with feed.subscribe() as sub: async for event in sub: ...`.
        """
        return Subscription(self, self._maxsize)

    def close(self) -> None:
        """Stop the feed and signal every subscriber to finish.

        Idempotent: a second call returns immediately, so the __main__ Server
        subclass (which closes at shutdown start) and the lifespan `finally`
        backstop can both call it safely. The sentinel is delivered drop-oldest so
        it always lands even on a full queue, guaranteeing every active
        Subscription's `__anext__` raises StopAsyncIteration.
        """
        if self._closed:
            return
        self._closed = True
        for queue in self._subscribers:
            self._offer(queue, None)
