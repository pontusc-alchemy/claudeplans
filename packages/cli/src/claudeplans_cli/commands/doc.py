"""`claudeplans doc <verb>` — document-level commands.

Reads project the fetched document client-side (fields/section/phase) so an agent
narrows a view without a second request. link/unlink read-modify-write the
research-ref set because the service exposes only an absolute set of the whole list.

Typer's option/argument descriptors are bound to module-level singletons (not inline
defaults) because ruff B008 forbids function calls in argument defaults; the
descriptor is shared and immutable, so a singleton is the sanctioned form.
"""

import json
import sys
from typing import Annotated

import typer

from claudeplans_contracts import (
    DocStatus,
    DocType,
    DocumentCreate,
    ValidationError,
    unlink_research_ref,
)

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit, emit_obj, emit_phases, emit_write

app = typer.Typer(no_args_is_help=True)

_TYPE = typer.Option("--type")
_FROM_JSON = typer.Option(
    "--from-json",
    help=(
        "'-' for stdin, or a literal JSON string. "
        "Accepts the full DocumentCreate shape — express the entire scaffold "
        "in one call, including nested sections and phases-with-tasks. "
        "Shape: {type, slug, title, status?(draft), date?, description?, "
        "frontmatter{}, research_refs[], primary_research_ref?, "
        "sections:[{anchor, heading, body?, level?(1-6)}], "
        "phases:[{slug, name, status?(todo), tasks:[{text, checked?(false)}]}]}. "
        'Example: \'{"type":"plan","slug":"p","title":"P",'
        '"sections":[{"anchor":"intro","heading":"Intro"}],'
        '"phases":[{"slug":"ph1","name":"Phase 1","tasks":[{"text":"do x"}]}]}\''
    ),
)
_SLUG = typer.Option(help="required unless --from-json (which carries its own slug)")
_TITLE = typer.Option()
_FIELDS = typer.Option(help="comma-separated")
_SECTION = typer.Option()
_PHASE = typer.Option()
_REV = typer.Option(
    "--rev",
    help="current rev; this write is position-sensitive (see 'doc rev')",
)
_STATUS_VALUE = typer.Argument()
_REF = typer.Argument()
_PRIMARY = typer.Option("--primary")
_SET_TITLE = typer.Option("--title")
_SET_DESCRIPTION = typer.Option("--description")
_SET_DATE = typer.Option("--date")
_SET_FRONTMATTER = typer.Option(
    "--frontmatter",
    help="JSON object; REPLACES the entire frontmatter dict (omitted keys are lost).",
)


@app.command()
@handle_errors
def create(
    ctx: typer.Context,
    project: str,
    type_: Annotated[DocType | None, _TYPE] = None,
    from_json: Annotated[str | None, _FROM_JSON] = None,
    slug: Annotated[str | None, _SLUG] = None,
    title: Annotated[str | None, _TITLE] = None,
) -> None:
    """Create a document from a full JSON body or from --type/--slug/--title."""
    c: AppContext = ctx.obj
    if from_json is not None:
        raw = sys.stdin.read() if from_json == "-" else from_json
        payload = DocumentCreate.model_validate_json(raw)
    else:
        # Validate from a dict so missing flags surface as pydantic ValidationError
        # (-> exit 4) rather than a static type error on the constructor.
        payload = DocumentCreate.model_validate(
            {"type": type_, "slug": slug, "title": title}
        )
    reply = c.client.create_document(c.uid, project, payload.model_dump(mode="json"))
    emit_write(reply, full=c.full, slice_="create")


@app.command()
@handle_errors
def get(
    ctx: typer.Context,
    project: str,
    slug: str,
    fields: Annotated[str | None, _FIELDS] = None,
    section: Annotated[str | None, _SECTION] = None,
    phase: Annotated[str | None, _PHASE] = None,
) -> None:
    """Fetch a document, optionally projecting fields / a section / a phase."""
    c: AppContext = ctx.obj
    if sum(x is not None for x in (fields, section, phase)) > 1:
        raise ValidationError("choose at most one of --fields/--section/--phase")
    reply = c.client.get_document(c.uid, project, slug)
    field_list = [f.strip() for f in fields.split(",")] if fields is not None else None
    emit(reply, fields=field_list, section=section, phase=phase)


@app.command()
@handle_errors
def delete(
    ctx: typer.Context,
    project: str,
    slug: str,
    rev: Annotated[str, _REV],
) -> None:
    """Delete a document (conditional on --rev)."""
    c: AppContext = ctx.obj
    reply = c.client.delete_document(c.uid, project, slug, rev=rev)
    emit_write(reply, full=c.full)


@app.command()
@handle_errors
def status(
    ctx: typer.Context,
    project: str,
    slug: str,
    value: Annotated[DocStatus, _STATUS_VALUE],
) -> None:
    """Set a document's status."""
    c: AppContext = ctx.obj
    reply = c.client.set_document_status(c.uid, project, slug, value.value)
    emit_write(reply, full=c.full)


app.command("set-status")(status)


@app.command()
@handle_errors
def phases(ctx: typer.Context, project: str, slug: str) -> None:
    """List a document's phases."""
    c: AppContext = ctx.obj
    reply = c.client.get_document(c.uid, project, slug)
    emit_phases(reply)


@app.command()
@handle_errors
def link(
    ctx: typer.Context,
    project: str,
    slug: str,
    ref: Annotated[str, _REF],
    primary: Annotated[bool, _PRIMARY] = False,
) -> None:
    """Add a research ref (dedup, order-preserving); optionally make it primary."""
    c: AppContext = ctx.obj
    # GET-then-PUT is intentionally unguarded: single-writer local service, and the
    # PUT is an absolute set of the whole ref list (last-writer-wins).
    current = c.client.get_document(c.uid, project, slug)
    data = current.data or {}
    existing: list[str] = list(data.get("research_refs", []))
    existing_primary: str | None = data.get("primary_research_ref")
    new_refs = existing if ref in existing else [*existing, ref]
    new_primary = ref if primary else existing_primary
    reply = c.client.put_research_refs(c.uid, project, slug, new_refs, new_primary)
    emit_write(reply, full=c.full)


@app.command()
@handle_errors
def unlink(
    ctx: typer.Context,
    project: str,
    slug: str,
    ref: Annotated[str, _REF],
) -> None:
    """Remove a research ref; if it was primary, promote the next remaining ref."""
    c: AppContext = ctx.obj
    # GET-then-PUT is intentionally unguarded: single-writer local service, and the
    # PUT is an absolute set of the whole ref list (last-writer-wins).
    current = c.client.get_document(c.uid, project, slug)
    data = current.data or {}
    existing: list[str] = list(data.get("research_refs", []))
    existing_primary: str | None = data.get("primary_research_ref")
    new_refs, new_primary = unlink_research_ref(existing, existing_primary, ref)
    reply = c.client.put_research_refs(c.uid, project, slug, new_refs, new_primary)
    emit_write(reply, full=c.full)


@app.command("set")
@handle_errors
def set_meta(
    ctx: typer.Context,
    project: str,
    slug: str,
    title: Annotated[str | None, _SET_TITLE] = None,
    description: Annotated[str | None, _SET_DESCRIPTION] = None,
    date: Annotated[str | None, _SET_DATE] = None,
    frontmatter: Annotated[str | None, _SET_FRONTMATTER] = None,
) -> None:
    """Set document metadata fields (omitted flags are left unchanged)."""
    c: AppContext = ctx.obj
    # Parse inside the handle_errors boundary: a malformed --frontmatter is a client
    # error (-> exit 4), not an uncaught JSONDecodeError that escapes as exit 1.
    fm: dict | None = None
    if frontmatter is not None:
        try:
            fm = json.loads(frontmatter)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"--frontmatter is not valid JSON: {exc}") from exc
    reply = c.client.set_document_meta(
        c.uid,
        project,
        slug,
        title=title,
        description=description,
        date=date,
        frontmatter=fm,
    )
    emit_write(reply, full=c.full)


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    project: str,
    type_: Annotated[DocType | None, _TYPE] = None,
) -> None:
    """List all documents in a project, optionally filtered by --type."""
    c: AppContext = ctx.obj
    raw = c.client.list_docs(c.uid, project)
    if type_ is not None and isinstance(raw, dict):
        items = raw.get("items", [])
        filtered = [
            item
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict) and item.get("type") == type_.value
        ]
        result: object = {"project": raw.get("project"), "items": filtered}
    else:
        result = raw
    emit_obj({"data": result, "warnings": []})


@app.command()
@handle_errors
def rev(ctx: typer.Context, project: str, slug: str) -> None:
    """Print the current rev (ETag) for a document without fetching its body."""
    c: AppContext = ctx.obj
    emit_obj({"rev": c.client.get_rev(c.uid, project, slug)})


@app.command()
@handle_errors
def view(ctx: typer.Context, project: str, slug: str) -> None:
    """Print the rendered view URL for a document (no network request)."""
    c: AppContext = ctx.obj
    base = c.base_url.rstrip("/")
    emit_obj({"url": f"{base}/v1/users/{c.uid}/projects/{project}/docs/{slug}/view"})
