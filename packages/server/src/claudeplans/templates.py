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

from claudeplans_contracts import Document

from . import render
from .lineage import Lineage, PlanRef, ResearchNode
from .navigation import ProjectTree, UserEntry

_TEMPLATE_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(default=True, default_for_string=True),
)


def _section_context(doc: Document) -> list[dict[str, object]]:
    return [
        {
            "anchor": s.anchor,
            "heading": s.heading,
            "level": s.level,
            "body_html": render.render_markdown(s.body),
        }
        for s in doc.sections
    ]


def _phase_context(doc: Document) -> list[dict[str, object]]:
    return [
        {
            "slug": p.slug,
            "name": p.name,
            "status": p.status.value,
            "tasks": [{"text": t.text, "checked": t.checked} for t in p.tasks],
        }
        for p in doc.phases
    ]


def _doc_context(doc: Document) -> dict[str, object]:
    description_html = (
        render.render_markdown(doc.description) if doc.description else ""
    )
    return {
        "doc": doc,
        "description_html": description_html,
        "sections": _section_context(doc),
        "phases": _phase_context(doc),
    }


def render_doc_body(doc: Document) -> str:
    """Render the inner morph payload (the SSE frame body) for `doc`."""
    return env.get_template("_doc_body.html").render(**_doc_context(doc))


def render_page(
    doc: Document, events_url: str, sidebar: dict[str, object] | None = None
) -> str:
    """Render the full document page (the morph target wrapping the body)."""
    return env.get_template("document.html").render(
        title=doc.title, events_url=events_url, sidebar=sidebar, **_doc_context(doc)
    )


def render_lineage_page(
    lineage: Lineage,
    title: str,
    view_url: Callable[[str], str],
    sidebar: dict[str, object] | None = None,
) -> str:
    """Render the project lineage index. `view_url(slug)` builds each doc link."""
    research = [
        {
            "title": node.title,
            "view_url": view_url(node.slug),
            "plans": [
                {"title": p.title, "view_url": view_url(p.slug)} for p in node.plans
            ],
            "backlinks": [
                {"title": p.title, "view_url": view_url(p.slug)} for p in node.backlinks
            ],
        }
        for node in lineage.research
    ]
    unlinked = [
        {"title": p.title, "view_url": view_url(p.slug)} for p in lineage.unlinked_plans
    ]
    return env.get_template("lineage.html").render(
        title=title,
        lineage={"research": research, "unlinked_plans": unlinked},
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
    lineage_url: Callable[[str], str],
) -> dict[str, object]:
    """Build the render-ready sidebar context.

    Logic-free templates: every link URL and the active-entry (`current`) flags are
    computed here in Python, so `_sidebar.html` only iterates. `view_url(project,
    slug)` and `lineage_url(project)` are supplied by the route layer.
    """

    def _doc(project: str, ref: PlanRef | ResearchNode) -> dict[str, object]:
        return {
            "title": ref.title,
            "view_url": view_url(project, ref.slug),
            "current": project == current_project and ref.slug == current_slug,
            "status": ref.status.value,
            "type": ref.type.value,
        }

    proj_ctx: list[dict[str, object]] = []
    for pt in projects:
        research = [
            {
                **_doc(pt.project, n),
                "plans": [_doc(pt.project, p) for p in n.plans],
                "backlinks": [_doc(pt.project, p) for p in n.backlinks],
            }
            for n in pt.lineage.research
        ]
        unlinked = [_doc(pt.project, p) for p in pt.lineage.unlinked_plans]
        proj_ctx.append(
            {
                "project": pt.project,
                "lineage_url": lineage_url(pt.project),
                "current": pt.project == current_project,
                "is_current_page": pt.project == current_project
                and current_slug is None,
                "doc_count": pt.doc_count,
                "research": research,
                "unlinked_plans": unlinked,
            }
        )
    return {
        "users": [{"uid": u.uid, "name": u.name, "current": u.current} for u in users],
        "switch_base": "/v1/users/",
        "projects": proj_ctx,
    }
