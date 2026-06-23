"""Bounded LRU cache of rendered doc-body HTML, keyed by (doc key, rev).

The doc key is the full `owner/project/slug` storage key, NOT the bare slug (which
is only unique within an owner+project — the per-document `rev` counter restarts at
"1" for every doc, so a bare slug would collide across tenants at the same rev).

Rendering markdown -> sanitized HTML is pure CPU and the same (doc key, rev) is asked
for repeatedly (every SSE reconnect, every viewer of an unchanged doc), so memoize
it. The cache is SELF-INVALIDATING: a write produces a new rev, hence a new key, so
a stale body is never served; old revs simply age out by LRU. Bounding the size
caps memory for a long-lived process churning through many docs.
"""

from collections import OrderedDict
from collections.abc import Callable
from typing import Final


class FragmentCache:
    """LRU cache mapping (doc key, rev) to rendered doc-body HTML.

    The doc key is the full `owner/project/slug` storage key, not the bare slug.
    """

    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize: Final = maxsize
        # Insertion-ordered: move-to-end on hit, popitem(last=False) evicts oldest.
        self._entries: OrderedDict[tuple[str, str], str] = OrderedDict()

    def get_or_render(self, doc_key: str, rev: str, render: Callable[[], str]) -> str:
        """Return the cached body for (doc_key, rev), rendering and storing on a miss.

        No lock: a single uvicorn worker on one asyncio loop runs each callback to
        completion before the next, so the dict ops here are effectively atomic.
        """
        key = (doc_key, rev)
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached
        body = render()
        self._entries[key] = body
        if len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)
        return body
