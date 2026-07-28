"""The cache memoizes by (doc key, rev): a hit must not re-render, a new rev must.

These pin the self-invalidation contract (new rev = new key), the LRU bound so a
long-lived process can't grow the cache without limit, and tenant isolation: two
docs sharing a slug across owners (same rev "1") must not collide on the cache key.
`invalidate` covers the one case rev-keying can't self-invalidate: a deleted doc's
entries must be dropped before its slug can be re-created and restart at rev "1".
"""

from claudeplans.cache import FragmentCache


def test_hit_returns_cached_without_rerender() -> None:
    cache = FragmentCache()
    calls = 0

    def render() -> str:
        nonlocal calls
        calls += 1
        return "body"

    assert cache.get_or_render("s", "r1", render) == "body"
    assert cache.get_or_render("s", "r1", render) == "body"
    assert calls == 1


def test_new_rev_is_a_new_key() -> None:
    cache = FragmentCache()
    calls = 0

    def render() -> str:
        nonlocal calls
        calls += 1
        return f"body{calls}"

    cache.get_or_render("s", "r1", render)
    cache.get_or_render("s", "r2", render)
    assert calls == 2


def test_different_doc_keys_same_rev_do_not_collide() -> None:
    # The fs `rev` restarts at "1" per doc, so two docs sharing a slug across owners
    # land at the same rev. Keying on the full storage key keeps them isolated:
    # each must render its own body, never serve the other tenant's.
    cache = FragmentCache()

    alice = cache.get_or_render("alice/demo/p1", "1", lambda: "alice-body")
    bob = cache.get_or_render("bob/demo/p1", "1", lambda: "bob-body")

    assert alice == "alice-body"
    assert bob == "bob-body"


def test_lru_evicts_oldest() -> None:
    cache = FragmentCache(maxsize=2)
    counts: dict[str, int] = {}

    def make(rev: str) -> str:
        counts[rev] = counts.get(rev, 0) + 1
        return rev

    cache.get_or_render("s", "r1", lambda: make("r1"))  # {r1}
    cache.get_or_render("s", "r2", lambda: make("r2"))  # {r1, r2}
    cache.get_or_render("s", "r3", lambda: make("r3"))  # over -> evict r1 -> {r2, r3}
    # r1 was evicted, so re-accessing it re-renders; r3 was never evicted, so a hit.
    assert cache.get_or_render("s", "r1", lambda: make("r1")) == "r1"
    assert cache.get_or_render("s", "r3", lambda: make("r3")) == "r3"
    assert counts == {"r1": 2, "r2": 1, "r3": 1}


def test_lru_hit_refreshes_recency() -> None:
    # A hit must mark the entry most-recently-used, so the OTHER entry is evicted next.
    cache = FragmentCache(maxsize=2)
    counts: dict[str, int] = {}

    def make(rev: str) -> str:
        counts[rev] = counts.get(rev, 0) + 1
        return rev

    cache.get_or_render("s", "r1", lambda: make("r1"))  # {r1}
    cache.get_or_render("s", "r2", lambda: make("r2"))  # {r1, r2}
    cache.get_or_render("s", "r1", lambda: make("r1"))  # HIT -> r1 now newest
    cache.get_or_render("s", "r3", lambda: make("r3"))  # over -> evict r2 (oldest)
    # r1 stayed cached because the hit refreshed its recency: re-asking is a HIT, so
    # make is NOT called again (r1 still rendered exactly once).
    assert cache.get_or_render("s", "r1", lambda: make("r1")) == "r1"
    assert counts["r1"] == 1
    # r2 was the oldest and got evicted, so re-asking re-renders it.
    assert cache.get_or_render("s", "r2", lambda: make("r2")) == "r2"
    assert counts["r2"] == 2


def test_invalidate_drops_all_revs_of_the_doc_key() -> None:
    cache = FragmentCache()
    cache.get_or_render("s", "r1", lambda: "old-r1")
    cache.get_or_render("s", "r2", lambda: "old-r2")

    cache.invalidate("s")

    # Both revs were dropped, so re-asking re-renders rather than serving the stale
    # cached body (the delete-then-recreate scenario: the new incarnation restarts
    # at rev "1" and must not collide with a dead incarnation's entry).
    assert cache.get_or_render("s", "r1", lambda: "new-r1") == "new-r1"
    assert cache.get_or_render("s", "r2", lambda: "new-r2") == "new-r2"


def test_invalidate_leaves_other_doc_keys_untouched() -> None:
    cache = FragmentCache()
    cache.get_or_render("s1", "r1", lambda: "s1-body")
    cache.get_or_render("s2", "r1", lambda: "s2-body")

    cache.invalidate("s1")

    # s2's entry survives untouched (still a hit — never re-rendered).
    assert cache.get_or_render("s2", "r1", lambda: "s2-rerendered") == "s2-body"
