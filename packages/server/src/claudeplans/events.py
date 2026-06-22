"""In-process change feed — the single source of "something changed".

Subscribers: the SSE route (live view), the search index, and the render cache.
Per-subscriber queues are BOUNDED (drop-oldest / disconnect slow clients) so one
stuck reader cannot grow memory without bound. In-process => a single uvicorn
worker; a shared broker for multi-replica is deferred. Built out in the rendering
phase; this skeleton fixes the interface.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Event:
    """A change notification: which document changed, and its new rev."""

    key: str
    rev: str


class EventFeed:
    """Fan-out of change Events to bounded per-subscriber queues."""

    def publish(self, event: Event) -> None:
        """Offer `event` to every subscriber (drop-oldest if a queue is full)."""
        raise NotImplementedError("event feed lands in the rendering phase")

    def subscribe(self) -> AsyncIterator[Event]:
        """Yield Events until the subscriber disconnects, then unsubscribe."""
        raise NotImplementedError("event feed lands in the rendering phase")
