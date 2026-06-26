"""Derived lineage view: which plans descend from which research.

A pure projection over a set of Documents — no IO, no FastAPI. Plans reference
research by slug (`primary_research_ref` = the plan's main source; `research_refs`
= every source it cites). This folds that many-to-one graph into a render-ready
tree the lineage page walks: each research node carries the plans it primarily
spawned plus backlinks from plans that merely cite it, and orphans (no primary, or
a primary pointing nowhere) land in `unlinked_plans`.

Standalone research (no dependents) is just a node with empty `plans`/`backlinks`,
so it needs no separate bucket. Matching is slug-equality only; cross-namespace
lineage (a plan citing research under another owner/project) is out of scope for
this phase — all docs passed in come from one user+project listing.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from claudeplans_contracts import Document
from claudeplans_contracts.enums import DocStatus, DocType


@dataclass(frozen=True, slots=True)
class PlanRef:
    """A plan, reduced to what the lineage page needs to link and label it."""

    slug: str
    title: str
    owner_id: str
    project: str
    status: DocStatus
    type: DocType


@dataclass(frozen=True, slots=True)
class ResearchNode:
    """A research doc plus the plans related to it.

    `plans`: plans whose `primary_research_ref` is this node.
    `backlinks`: plans that cite this node in `research_refs` but NOT as primary.
    """

    slug: str
    title: str
    owner_id: str
    project: str
    status: DocStatus
    type: DocType
    plans: tuple[PlanRef, ...]
    backlinks: tuple[PlanRef, ...]


@dataclass(frozen=True, slots=True)
class Lineage:
    """The full derived tree: research roots (standalone = empty plans) + orphans."""

    research: tuple[ResearchNode, ...]
    unlinked_plans: tuple[PlanRef, ...]


def _plan_ref(doc: Document) -> PlanRef:
    return PlanRef(
        slug=doc.slug,
        title=doc.title,
        owner_id=doc.owner_id,
        project=doc.project,
        status=doc.status,
        type=doc.type,
    )


def build_lineage(docs: Iterable[Document]) -> Lineage:
    """Project `docs` into a lineage tree, sorted deterministically by slug.

    Total: empty input -> empty Lineage. A plan whose `primary_research_ref` points
    at a slug with no matching research doc is treated as unlinked (dangling ref),
    same as a plan with no primary at all.
    """
    docs = list(docs)
    research_docs = [d for d in docs if d.type is DocType.research]
    plan_docs = [d for d in docs if d.type is DocType.plan]
    research_slugs = {d.slug for d in research_docs}

    nodes: list[ResearchNode] = []
    for research in sorted(research_docs, key=lambda d: d.slug):
        primary = [
            _plan_ref(p) for p in plan_docs if p.primary_research_ref == research.slug
        ]
        backlinks = [
            _plan_ref(p)
            for p in plan_docs
            if research.slug in p.research_refs
            and p.primary_research_ref != research.slug
        ]
        nodes.append(
            ResearchNode(
                slug=research.slug,
                title=research.title,
                owner_id=research.owner_id,
                project=research.project,
                status=research.status,
                type=research.type,
                plans=tuple(sorted(primary, key=lambda r: r.slug)),
                backlinks=tuple(sorted(backlinks, key=lambda r: r.slug)),
            )
        )

    unlinked = [
        _plan_ref(p)
        for p in plan_docs
        if p.primary_research_ref is None
        or p.primary_research_ref not in research_slugs
    ]
    return Lineage(
        research=tuple(nodes),
        unlinked_plans=tuple(sorted(unlinked, key=lambda r: r.slug)),
    )
