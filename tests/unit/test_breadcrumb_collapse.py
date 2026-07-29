"""The breadcrumb's middle-collapse boundary (api.view._collapse_trail)."""

import pytest

from claudeplans.api.view import _collapse_trail


def _hops(n: int) -> list[dict[str, object]]:
    return [{"title": f"a{i}", "view_url": f"/{i}"} for i in range(n)]


def test_no_ancestors_renders_no_trail() -> None:
    assert _collapse_trail([]) is None


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_renders_in_full_up_to_four_ancestors(n: int) -> None:
    """head=1 + tail=2 + 1, counted over ancestors (the current doc is separate)."""
    trail = _collapse_trail(_hops(n))
    assert trail == _hops(n)


@pytest.mark.parametrize("n", [5, 6, 12])
def test_collapses_the_middle_past_the_boundary(n: int) -> None:
    trail = _collapse_trail(_hops(n))
    assert trail is not None
    assert len(trail) == 4
    assert trail[0] == _hops(n)[0]
    assert trail[-2:] == _hops(n)[-2:]
    assert trail[1]["elided"] is True


def test_the_ellipsis_always_stands_for_two_or_more_hops() -> None:
    """Full render at exactly one middle node, so a lone hidden hop never occurs."""
    for n in range(5, 12):
        trail = _collapse_trail(_hops(n))
        assert trail is not None
        assert str(trail[1]["title"]).count(",") + 1 >= 2


def test_the_ellipsis_names_the_elided_ancestors() -> None:
    """Assistive tech still reaches the hidden hops via title/aria-label."""
    trail = _collapse_trail(_hops(6))
    assert trail is not None
    assert trail[1]["title"] == "a1, a2, a3"


def test_the_root_and_the_nearest_ancestors_always_survive() -> None:
    trail = _collapse_trail(_hops(9))
    assert trail is not None
    assert [h.get("title") for h in trail] == [
        "a0",
        "a1, a2, a3, a4, a5, a6",
        "a7",
        "a8",
    ]
