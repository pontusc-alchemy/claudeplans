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
from typing import Any, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from claudeplans_contracts import Document, Phase, SectionPlacement

from . import render
from .lineage import DocNode, Lineage, walk
from .navigation import ProjectTree, UserEntry

_TEMPLATE_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(default=True, default_for_string=True),
)


def set_app_version(version: str) -> None:
    """Expose the running app version to every template as `app_version`."""
    # cast: ty narrows `env.globals` to Jinja's default-namespace literal dict,
    # which rejects plain-str values; the attribute is a str->Any mapping.
    cast("dict[str, Any]", env.globals)["app_version"] = version


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
    lineage_trail: list[dict[str, object]] | None = None,
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
    """Project a Lineage into the recursive `{roots}` shape the template walks.
    `view_url(slug)` builds each doc link."""

    def node(n: DocNode) -> dict[str, object]:
        return {
            "title": n.title,
            "view_url": view_url(n.slug),
            "children": [node(c) for c in n.children],
        }

    return {"roots": [node(r) for r in lineage.roots]}


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
    archived_ctx = _lineage_projection(archived, view_url) if archived.roots else None
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

    def _doc(project: str, node: DocNode) -> dict[str, object]:
        return {
            "title": node.title,
            "view_url": view_url(project, node.slug),
            "current": project == current_project and node.slug == current_slug,
            "status": node.status.value,
            "type": node.type.value,
            # Collapse key for a node that has children. Shares the project
            # namespace via "//", which no real project slug can contain.
            "key": f"{project}//doc/{node.slug}",
            "children": [_doc(project, c) for c in node.children],
        }

    def _archived_slugs(lineage: Lineage) -> set[str]:
        """Every doc slug in the archived tree, at any depth."""
        return {n.slug for n in walk(lineage.roots)}

    def _roots(project: str, lineage: Lineage) -> list[dict[str, object]]:
        return [_doc(project, r) for r in lineage.roots]

    proj_ctx: list[dict[str, object]] = []
    for pt in projects:
        roots = _roots(pt.project, pt.lineage)
        archived_roots = _roots(pt.project, pt.archived)
        # Every archived doc at any depth. backlinks are not counted: they are
        # duplicates of a doc already counted at its own place in the tree.
        archived_count = len(list(walk(pt.archived.roots)))
        proj_ctx.append(
            {
                "project": pt.project,
                "name": pt.name,
                "current": pt.project == current_project,
                "doc_count": pt.doc_count,
                "roots": roots,
                "archived": (
                    {
                        "roots": archived_roots,
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
