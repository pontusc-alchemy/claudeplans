"""Jinja rendering of the live-view pages — the one place HTML is assembled.

The security contract lives here: section/description bodies are run through
`render.render_markdown` (markdown -> nh3-sanitized HTML) in PYTHON, then handed to
the template as pre-rendered strings marked `| safe`. Everything else (titles,
slugs, statuses) flows through Jinja's autoescape. So the ONLY HTML marked safe is
nh3 output; the templates stay logic-free (no Python called from Jinja).

A single module-level `Environment` is built once (templates are immutable on disk);
`autoescape=True` is the default-deny that makes the `| safe` markers the explicit,
auditable exceptions.
"""

from collections.abc import Callable
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from claudeplans_contracts import Document, Phase, SectionPlacement

from . import render
from .lineage import Lineage, PlanRef, ResearchNode
from .navigation import ProjectTree, UserEntry

_TEMPLATE_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(default=True, default_for_string=True),
)


def _phase_overview(doc: Document) -> list[dict[str, object]]:
    """The top summary list: one entry per phase (name + status), in order."""
    return [
        {"slug": p.slug, "name": p.name, "status": p.status.value} for p in doc.phases
    ]


def _section_block(
    anchor: str, heading: str, level: int, body: str
) -> dict[str, object]:
    return {
        "kind": "section",
        "anchor": anchor,
        "heading": heading,
        "level": level,
        "body_html": render.render_markdown(body),
    }


def _phase_block(phase: Phase) -> dict[str, object]:
    return {
        "kind": "phase",
        "slug": phase.slug,
        "name": phase.name,
        "status": phase.status.value,
        "prose_html": render.render_markdown(phase.intro) if phase.intro else "",
        "exit_html": (
            render.render_markdown(phase.exit_criteria) if phase.exit_criteria else ""
        ),
        "notes_html": render.render_markdown(phase.notes) if phase.notes else "",
        "tasks": [{"text": t.text, "checked": t.checked} for t in phase.tasks],
    }


def _blocks(doc: Document) -> list[dict[str, object]]:
    """The linear render flow: lead sections (in list order), then every phase (in
    list order), then trail sections. `Section.placement` buckets a section before or
    after the phase group; ordering within a bucket is list order. There is no longer
    any anchor==slug coupling — a phase's prose lives in its own fields."""
    blocks: list[dict[str, object]] = [
        _section_block(s.anchor, s.heading, s.level, s.body)
        for s in doc.sections
        if s.placement is SectionPlacement.lead
    ]
    blocks.extend(_phase_block(p) for p in doc.phases)
    blocks.extend(
        _section_block(s.anchor, s.heading, s.level, s.body)
        for s in doc.sections
        if s.placement is SectionPlacement.trail
    )
    return blocks


def _doc_context(doc: Document) -> dict[str, object]:
    description_html = (
        render.render_markdown(doc.description) if doc.description else ""
    )
    return {
        "doc": doc,
        "description_html": description_html,
        "phases": _phase_overview(doc),
        "blocks": _blocks(doc),
    }


def render_doc_body(doc: Document) -> str:
    """Render the inner morph payload (the SSE frame body) for `doc`."""
    return env.get_template("_doc_body.html").render(**_doc_context(doc))


def render_sidebar(sidebar: dict[str, object]) -> str:
    """Render the sidebar partial to an HTML string (SSE sidebar frames)."""
    return env.get_template("_sidebar.html").render(sidebar=sidebar)


def render_page(
    doc: Document,
    events_url: str,
    sidebar: dict[str, object] | None = None,
    lineage_trail: dict[str, object] | None = None,
    subdoc_index: list[dict[str, object]] | None = None,
) -> str:
    """Render the full document page (the morph target wrapping the body)."""
    return env.get_template("document.html").render(
        title=doc.title,
        events_url=events_url,
        sidebar=sidebar,
        lineage_trail=lineage_trail,
        subdoc_index=subdoc_index,
        **_doc_context(doc),
    )


def _lineage_projection(
    lineage: Lineage, view_url: Callable[[str], str]
) -> dict[str, object]:
    """Project a Lineage into the `{research, unlinked_plans}` shape the lineage
    template walks. `view_url(slug)` builds each doc link."""
    research = [
        {
            "title": node.title,
            "view_url": view_url(node.slug),
            "plans": [
                {"title": p.title, "view_url": view_url(p.slug)} for p in node.plans
            ],
        }
        for node in lineage.research
    ]
    unlinked = [
        {"title": p.title, "view_url": view_url(p.slug)} for p in lineage.unlinked_plans
    ]
    return {"research": research, "unlinked_plans": unlinked}


def render_lineage_page(
    lineage: Lineage,
    title: str,
    view_url: Callable[[str], str],
    archived: Lineage,
    sidebar: dict[str, object] | None = None,
) -> str:
    """Render the project lineage index. `view_url(slug)` builds each doc link.

    `archived` is the same lineage fold over archived-status docs; it renders as a
    separate, collapsed group and is `None` in the template context when empty.
    """
    archived_ctx = (
        _lineage_projection(archived, view_url)
        if archived.research or archived.unlinked_plans
        else None
    )
    return env.get_template("lineage.html").render(
        title=title,
        lineage=_lineage_projection(lineage, view_url),
        archived=archived_ctx,
        sidebar=sidebar,
    )


def render_landing_page(title: str, sidebar: dict[str, object] | None = None) -> str:
    """Render the minimal landing page: sidebar chrome + an empty welcome pane."""
    return env.get_template("landing.html").render(title=title, sidebar=sidebar)


def render_user_picker(
    title: str, users: list[UserEntry], user_url: Callable[[str], str]
) -> str:
    """Render the root user-picker: each user links into their own tree.

    `user_url(uid)` is supplied by the route layer (like the other renderers), so
    this module stays unaware of the route shape.
    """
    return env.get_template("users.html").render(
        title=title,
        users=[{"name": u.name, "url": user_url(u.uid)} for u in users],
    )


def build_sidebar(
    *,
    users: list[UserEntry],
    projects: list[ProjectTree],
    current_uid: str,
    current_project: str | None,
    current_slug: str | None,
    view_url: Callable[[str, str], str],
) -> dict[str, object]:
    """Build the render-ready sidebar context.

    Logic-free templates: every link URL and the active-entry (`current`) flags are
    computed here in Python, so `_sidebar.html` only iterates. `view_url(project,
    slug)` is supplied by the route layer.
    """

    def _doc(project: str, ref: PlanRef | ResearchNode) -> dict[str, object]:
        return {
            "title": ref.title,
            "view_url": view_url(project, ref.slug),
            "current": project == current_project and ref.slug == current_slug,
            "status": ref.status.value,
            "type": ref.type.value,
        }

    def _archived_slugs(lineage: Lineage) -> set[str]:
        """Every doc slug in the archived lineage (backlinks are duplicates)."""
        return (
            {n.slug for n in lineage.research}
            | {p.slug for n in lineage.research for p in n.plans}
            | {p.slug for p in lineage.unlinked_plans}
        )

    def _research_and_unlinked(
        project: str, lineage: Lineage
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        research = [
            {
                **_doc(project, n),
                "plans": [_doc(project, p) for p in n.plans],
            }
            for n in lineage.research
        ]
        unlinked = [_doc(project, p) for p in lineage.unlinked_plans]
        return research, unlinked

    proj_ctx: list[dict[str, object]] = []
    for pt in projects:
        research, unlinked = _research_and_unlinked(pt.project, pt.lineage)
        archived_research, archived_unlinked = _research_and_unlinked(
            pt.project, pt.archived
        )
        # Count = every archived doc (research + its primary plans + unlinked
        # plans); backlinks are duplicates of a plan counted under its primary
        # research node, so they are never counted here.
        archived_count = (
            len(pt.archived.research)
            + sum(len(n.plans) for n in pt.archived.research)
            + len(pt.archived.unlinked_plans)
        )
        proj_ctx.append(
            {
                "project": pt.project,
                "name": pt.name,
                "current": pt.project == current_project,
                "doc_count": pt.doc_count,
                "research": research,
                "unlinked_plans": unlinked,
                "archived": (
                    {
                        "research": archived_research,
                        "unlinked_plans": archived_unlinked,
                        "count": archived_count,
                        # Auto-expand when the doc being viewed is archived;
                        # stored user intent still wins on the client (ui.js).
                        "open": pt.project == current_project
                        and current_slug in _archived_slugs(pt.archived),
                    }
                    if archived_count
                    else None
                ),
            }
        )
    return {
        "users": [{"uid": u.uid, "name": u.name, "current": u.current} for u in users],
        "switch_base": "/v1/users/",
        "projects": proj_ctx,
        "current_uid": current_uid,
        "current_project": current_project,
    }
