"""Lineage is a pure projection, so these drive it with plain Documents.
They pin the n-level fold: nesting, roots, placement, backlinks, order, depth cap."""

from claudeplans.lineage import build_lineage, walk
from claudeplans_contracts import MAX_LINEAGE_DEPTH, Document
from claudeplans_contracts.enums import DocStatus, DocType


def _doc(
    slug: str,
    parent: str | None = None,
    refs: list[str] | None = None,
    type: DocType = DocType.plan,
    status: DocStatus = DocStatus.draft,
) -> Document:
    # The model requires the primary parent to also be a member of research_refs.
    merged = ([parent] if parent else []) + (refs or [])
    return Document(
        type=type,
        project="demo",
        slug=slug,
        title=slug,
        owner_id="dev",
        status=status,
        research_refs=list(dict.fromkeys(merged)),
        primary_parent_ref=parent,
    )


def _slugs(nodes: tuple) -> list[str]:
    return [n.slug for n in nodes]


def test_empty_input_yields_empty_lineage() -> None:
    lineage = build_lineage([])
    assert lineage.roots == ()
    assert lineage.over_cap == ()


def test_chain_nests_four_levels_deep() -> None:
    lineage = build_lineage([_doc("a"), _doc("b", "a"), _doc("c", "b"), _doc("d", "c")])
    assert _slugs(lineage.roots) == ["a"]
    a = lineage.roots[0]
    assert _slugs(a.children) == ["b"]
    assert _slugs(a.children[0].children) == ["c"]
    assert _slugs(a.children[0].children[0].children) == ["d"]
    assert a.children[0].children[0].children[0].children == ()


def test_type_is_orthogonal_to_tree_position() -> None:
    # A plan parents research, which parents a plan again: any type at any depth.
    lineage = build_lineage(
        [
            _doc("a", type=DocType.plan),
            _doc("b", "a", type=DocType.research),
            _doc("c", "b", type=DocType.plan),
        ]
    )
    a = lineage.roots[0]
    assert a.type is DocType.plan
    assert a.children[0].type is DocType.research
    assert a.children[0].children[0].type is DocType.plan


def test_docs_without_a_parent_are_roots() -> None:
    lineage = build_lineage([_doc("a"), _doc("b"), _doc("c", "a")])
    assert _slugs(lineage.roots) == ["a", "b"]
    assert _slugs(lineage.roots[0].children) == ["c"]
    assert lineage.roots[1].children == ()


def test_dangling_parent_degrades_to_root() -> None:
    # The parent slug is absent from the input set: surface the doc, never hide it.
    lineage = build_lineage([_doc("a"), _doc("b", "ghost")])
    assert _slugs(lineage.roots) == ["a", "b"]
    assert lineage.roots[1].children == ()


def test_self_parent_is_a_root_not_a_loop() -> None:
    # The model rejects self-parenting, so a corrupt stored doc needs model_construct.
    rogue = Document.model_construct(
        type=DocType.plan,
        project="demo",
        slug="a",
        title="a",
        owner_id="dev",
        research_refs=["a"],
        primary_parent_ref="a",
    )
    lineage = build_lineage([rogue])
    assert _slugs(lineage.roots) == ["a"]
    assert lineage.roots[0].children == ()


def test_citing_an_ancestor_does_not_duplicate_placement() -> None:
    # `c` cites root `a` as a plain ref while its primary is `b`. It must appear
    # exactly once in the tree, under `b` only.
    lineage = build_lineage([_doc("a"), _doc("b", "a"), _doc("c", "b", refs=["a"])])
    assert [n.slug for n in walk(lineage.roots)] == ["a", "b", "c"]
    a = lineage.roots[0]
    assert _slugs(a.children) == ["b"]
    assert _slugs(a.children[0].children) == ["c"]


def test_non_primary_citation_becomes_a_backlink() -> None:
    lineage = build_lineage([_doc("a"), _doc("b"), _doc("c", "b", refs=["a"])])
    by_slug = {n.slug: n for n in walk(lineage.roots)}
    assert _slugs(by_slug["a"].backlinks) == ["c"]
    assert by_slug["a"].children == ()
    assert by_slug["b"].backlinks == ()
    assert _slugs(by_slug["b"].children) == ["c"]


def test_roots_and_children_are_sorted_by_slug() -> None:
    lineage = build_lineage(
        [_doc("rb"), _doc("ra"), _doc("pb", "ra"), _doc("pa", "ra")]
    )
    assert _slugs(lineage.roots) == ["ra", "rb"]
    assert _slugs(lineage.roots[0].children) == ["pa", "pb"]


def test_over_cap_children_are_named_not_silently_dropped() -> None:
    chain = [_doc("d00")] + [
        _doc(f"d{i:02d}", f"d{i - 1:02d}") for i in range(1, MAX_LINEAGE_DEPTH + 2)
    ]
    lineage = build_lineage(chain)
    rendered = [n.slug for n in walk(lineage.roots)]
    assert len(rendered) == MAX_LINEAGE_DEPTH
    assert rendered[-1] == f"d{MAX_LINEAGE_DEPTH - 1:02d}"
    assert lineage.over_cap == (f"d{MAX_LINEAGE_DEPTH:02d}",)


def test_walk_yields_every_node_depth_first() -> None:
    lineage = build_lineage([_doc("a"), _doc("b", "a"), _doc("c", "a"), _doc("d", "b")])
    assert [n.slug for n in walk(lineage.roots)] == ["a", "b", "d", "c"]


def test_nodes_carry_status_and_type() -> None:
    lineage = build_lineage(
        [
            _doc("a", type=DocType.research, status=DocStatus.active),
            _doc("b", "a", type=DocType.plan, status=DocStatus.done),
        ]
    )
    a = lineage.roots[0]
    assert (a.status, a.type) == (DocStatus.active, DocType.research)
    assert (a.children[0].status, a.children[0].type) == (DocStatus.done, DocType.plan)
