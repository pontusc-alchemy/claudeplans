"""Derived document tree: which docs nest under which, to any depth — a pure
projection over Documents, no IO. See `build_lineage` for the fold and its rules."""

import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from claudeplans_contracts import MAX_LINEAGE_DEPTH, Document
from claudeplans_contracts.enums import DocStatus, DocType

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AncestorRef:
    """One hop on a doc's upward trail: the slug to link and the title to label."""

    slug: str
    title: str


@dataclass(frozen=True, slots=True)
class ChildRef:
    """A doc's sub-doc: the slug to link and the title to label."""

    slug: str
    title: str


@dataclass(frozen=True, slots=True)
class DocNode:
    """A doc plus the docs nested beneath it.

    `children`: docs whose `primary_parent_ref` is this node, recursively.
    `backlinks`: docs citing this node in `research_refs` but NOT as their parent.

    `type` is orthogonal to tree position — any doc may parent any doc. The badge
    says what a doc is, the tree says where it lives.
    """

    slug: str
    title: str
    owner_id: str
    project: str
    status: DocStatus
    type: DocType
    children: tuple[DocNode, ...] = ()
    backlinks: tuple[ChildRef, ...] = ()


@dataclass(frozen=True, slots=True)
class Lineage:
    """The derived forest: every doc with no resolvable parent, plus its subtree.

    `over_cap` names children elided at MAX_LINEAGE_DEPTH, so a too-deep chain is
    reportable rather than silently short.
    """

    roots: tuple[DocNode, ...] = ()
    over_cap: tuple[str, ...] = ()


def _child_ref(doc: Document) -> ChildRef:
    return ChildRef(slug=doc.slug, title=doc.title)


def build_lineage(docs: Iterable[Document]) -> Lineage:
    """Project `docs` into a nested tree, sorted deterministically by slug.

    Nesting is derived here at read time and never stored as structure, so a doc
    reparents by changing one field.

    Total: empty input -> empty Lineage. A doc whose `primary_parent_ref` names a slug
    not present is a root, exactly like a doc with no parent — a dangling pointer
    degrades to "top level" rather than hiding the doc.

    Placement keys on `primary_parent_ref` EQUALITY ONLY. The model guarantees the
    parent is also in `research_refs`, so gathering children by `research_refs`
    membership would place a doc under every ref it cites, and could loop where a doc
    cites an ancestor. `research_refs` drives backlinks, never placement.

    O(n): one pass builds a `parent_slug -> [child]` adjacency map, then the recursion
    walks it. Re-scanning every doc per node would be O(n^2).
    """
    by_slug = {d.slug: d for d in sorted(docs, key=lambda d: d.slug)}

    children_of: dict[str, list[Document]] = {}
    roots: list[Document] = []
    for doc in by_slug.values():
        parent = doc.primary_parent_ref
        if parent is not None and parent in by_slug and parent != doc.slug:
            children_of.setdefault(parent, []).append(doc)
        else:
            roots.append(doc)

    backlinks_of: dict[str, list[ChildRef]] = {}
    for doc in by_slug.values():
        for ref in doc.research_refs:
            if ref in by_slug and ref != doc.primary_parent_ref:
                backlinks_of.setdefault(ref, []).append(_child_ref(doc))

    over_cap: list[str] = []

    def node(doc: Document, depth: int) -> DocNode:
        kids: list[Document] = children_of.get(doc.slug, [])
        if kids and depth >= MAX_LINEAGE_DEPTH:
            # Loud, not silent: a doc dropped without a trace is indistinguishable
            # from one that was never created.
            over_cap.extend(k.slug for k in kids)
            logger.warning(
                "lineage depth cap %d reached at %r; %d subtree(s) not rendered",
                MAX_LINEAGE_DEPTH,
                doc.slug,
                len(kids),
            )
            kids = []
        return DocNode(
            slug=doc.slug,
            title=doc.title,
            owner_id=doc.owner_id,
            project=doc.project,
            status=doc.status,
            type=doc.type,
            children=tuple(node(k, depth + 1) for k in kids),
            backlinks=tuple(backlinks_of.get(doc.slug, [])),
        )

    return Lineage(
        roots=tuple(node(d, 1) for d in roots),
        over_cap=tuple(sorted(over_cap)),
    )


def walk(nodes: Iterable[DocNode]) -> Iterator[DocNode]:
    """Every node in the forest, depth-first.

    Callers needing a flat view (counts, slug sets) use this rather than
    re-implementing the recursion and disagreeing about it.
    """
    for n in nodes:
        yield n
        yield from walk(n.children)
