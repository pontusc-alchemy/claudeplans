"""Collapsible sidebar nodes: a disclosure control exactly where a subtree exists."""

import re
from pathlib import Path

import httpx
from _view_harness import DOCS, client_for

VIEW = "/v1/users/dev/projects/demo/docs/{}/view"


async def _create(
    client: httpx.AsyncClient, slug: str, parent: str | None = None
) -> None:
    body: dict[str, object] = {"type": "plan", "slug": slug, "title": slug}
    if parent is not None:
        body["primary_parent_ref"] = parent
        body["research_refs"] = [parent]
    resp = await client.post(DOCS, json=body)
    assert resp.status_code == 201, resp.text


def _sidebar(body: str) -> str:
    """The sidebar markup only, so doc-body content cannot satisfy an assertion."""
    start = body.index('<aside class="sidebar"')
    return body[start : body.index("</aside>", start)]


async def test_parent_node_renders_a_disclosure_control(tmp_path: Path) -> None:
    async with client_for(tmp_path) as client:
        await _create(client, "parent")
        await _create(client, "child", parent="parent")
        side = _sidebar((await client.get(VIEW.format("parent"))).text)
    assert '<details class="doc-branch" data-project="demo//doc/parent" open>' in side
    assert '<summary class="doc-twisty" aria-label="Toggle parent"></summary>' in side


async def test_title_link_is_never_inside_the_summary(tmp_path: Path) -> None:
    """Enter on a link inside a <summary> both navigates AND toggles the node.

    Verified in Chromium: the toggle also persists, so a keyboard user silently
    inverts that node's stored disclosure state. The twisty holds only its marker.
    """
    async with client_for(tmp_path) as client:
        await _create(client, "parent")
        await _create(client, "child", parent="parent")
        side = _sidebar((await client.get(VIEW.format("parent"))).text)
    for summary in re.findall(r"<summary class=\"doc-twisty\".*?</summary>", side):
        assert "<a" not in summary, summary


async def test_leaf_node_renders_no_disclosure_control(tmp_path: Path) -> None:
    """A twisty on a leaf would promise a subtree that is not there.

    The steward reads the tree by skimming, so an affordance that opens nothing is
    a lie about structure, not a cosmetic issue.
    """
    async with client_for(tmp_path) as client:
        await _create(client, "parent")
        await _create(client, "child", parent="parent")
        side = _sidebar((await client.get(VIEW.format("parent"))).text)
    assert "doc/child" not in side
    assert side.count('class="doc-branch"') == 1


async def test_every_node_keeps_its_full_affordance_set(tmp_path: Path) -> None:
    async with client_for(tmp_path) as client:
        await _create(client, "parent")
        await _create(client, "child", parent="parent")
        side = _sidebar((await client.get(VIEW.format("parent"))).text)
    for slug in ("parent", "child"):
        link = re.search(
            rf'<a class="doc-node-title"[^>]*docs/{slug}/view.*?</a>', side
        )
        assert link is not None, slug
        assert "status-dot" in link.group(0)
        assert "doc-type" in link.group(0)


async def test_nodes_are_open_by_default_at_every_depth(tmp_path: Path) -> None:
    """Collapse is the steward's act, not the system's guess.

    Collapsed-by-default would hide exactly what the skim checks for.
    """
    async with client_for(tmp_path) as client:
        await _create(client, "a")
        await _create(client, "b", parent="a")
        await _create(client, "c", parent="b")
        side = _sidebar((await client.get(VIEW.format("c"))).text)
    assert side.count('class="doc-branch"') == 2
    assert side.count('class="doc-branch" data-project="demo//doc/a" open') == 1
    assert side.count('class="doc-branch" data-project="demo//doc/b" open') == 1


async def test_deep_subtree_nests_each_level(tmp_path: Path) -> None:
    async with client_for(tmp_path) as client:
        await _create(client, "a")
        await _create(client, "b", parent="a")
        await _create(client, "c", parent="b")
        side = _sidebar((await client.get(VIEW.format("a"))).text)
    a = side.index('data-project="demo//doc/a"')
    b = side.index('data-project="demo//doc/b"')
    # Between a and b a child list opens and none closes, so b sits inside a's
    # subtree rather than beside it.
    between = side[a:b]
    assert '<ul class="doc-tree">' in between
    assert "</ul>" not in between


async def test_collapse_keys_are_unique_per_document(tmp_path: Path) -> None:
    """Two parents sharing a key would toggle each other through ui.js persistence."""
    async with client_for(tmp_path) as client:
        await _create(client, "one")
        await _create(client, "two")
        await _create(client, "one-kid", parent="one")
        await _create(client, "two-kid", parent="two")
        side = _sidebar((await client.get(VIEW.format("one"))).text)
    keys = re.findall(r'class="doc-branch" data-project="([^"]+)"', side)
    assert sorted(keys) == ["demo//doc/one", "demo//doc/two"]


def _rule_body(css: str, selector: str) -> str:
    rest = css[css.index(selector) :]
    return rest[: rest.index("}")]


async def test_closed_details_content_is_display_none(tmp_path: Path) -> None:
    """Closes issue #26: Chromium hides closed-details content with
    content-visibility, which leaves the anchors targetable by link-hint tools."""
    async with client_for(tmp_path) as client:
        css = (await client.get("/assets/css/app.css")).text
    assert "display: none;" in _rule_body(css, ".sidebar details:not([open]) > *:not")


async def test_collapsed_twisty_hides_its_sibling_subtree(tmp_path: Path) -> None:
    """The subtree sits beside the twisty, not inside it, so it needs its own rule."""
    async with client_for(tmp_path) as client:
        css = (await client.get("/assets/css/app.css")).text
    assert "display: none;" in _rule_body(css, ".sidebar .doc-branch:not([open]) ~ ")
