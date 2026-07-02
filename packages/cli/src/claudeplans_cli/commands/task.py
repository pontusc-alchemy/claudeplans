"""`claudeplans task <verb>` — task-level commands.

Every task mutation except `add` is conditional (--rev): tasks are addressed by
positional index, so the service gates index-based writes with If-Match to catch a
concurrent reorder. Typer descriptors are module-level singletons to satisfy B008.
"""

from typing import Annotated

import typer

from claudeplans_contracts import ValidationError

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit_task_added, emit_write

app = typer.Typer(no_args_is_help=True)

_TEXT = typer.Argument()
_TASK_INDEX = typer.Argument()
_REV = typer.Option(
    "--rev",
    help="current rev; this write is position-sensitive (see 'doc rev')",
)
_CHECKED = typer.Option("--checked/--unchecked")
_INDICES = typer.Argument(
    help="0-based task indices to set; omit and pass --all for the whole phase"
)
_ALL = typer.Option(
    "--all",
    help="target every task in the phase (rev-free; excludes explicit indices)",
)
_SET_CHECKED_REV = typer.Option(
    "--rev",
    help="current rev; required only when targeting explicit indices (see 'doc rev')",
)
_AT = typer.Option(
    "--at",
    help="0-based insert position; appends if omitted. Unconditional (no --rev).",
)


@app.command()
@handle_errors
def add(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    text: Annotated[str, _TEXT],
    at: Annotated[int | None, _AT] = None,
    checked: Annotated[bool, _CHECKED] = False,
) -> None:
    """Append a task to a phase, or insert at --at if given.

    Use --checked/--unchecked to set the initial state; defaults to unchecked.
    For bulk authoring (many tasks, or whole phases-with-tasks at once) there is
    no per-task bulk verb — pass the full body via `doc create --from-json`.
    """
    c: AppContext = ctx.obj
    reply = c.client.add_task(c.uid, project, slug, phase_slug, text, at, checked)
    data = reply.data or {}
    phase = next(
        (p for p in data.get("phases", []) if p.get("slug") == phase_slug), None
    )
    tasks = phase.get("tasks", []) if phase else []
    index = at if at is not None else len(tasks) - 1
    # Echo the just-added task's text/checked so the reply is self-verifying.
    added = tasks[index] if 0 <= index < len(tasks) else None
    task_text = added.get("text") if isinstance(added, dict) else None
    task_checked = added.get("checked") if isinstance(added, dict) else None
    emit_task_added(
        reply,
        phase_slug=phase_slug,
        index=index,
        text=task_text,
        checked=task_checked,
        full=c.full,
    )


@app.command()
@handle_errors
def toggle(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: Annotated[int, _TASK_INDEX],
    rev: Annotated[str, _REV],
    checked: Annotated[bool, _CHECKED] = True,
) -> None:
    """Set a task checked/unchecked via --checked/--unchecked (conditional on --rev).

    Despite the name this is an absolute set, not a flip — identical single-index
    effect to `set-checked`, which additionally offers `--all` and multi-index forms.
    """
    c: AppContext = ctx.obj
    reply = c.client.toggle_task(
        c.uid, project, slug, phase_slug, task_index, checked, rev=rev
    )
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")


@app.command("set-checked")
@handle_errors
def set_checked(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    indices: Annotated[list[int] | None, _INDICES] = None,
    all_: Annotated[bool, _ALL] = False,
    checked: Annotated[bool, _CHECKED] = True,
    rev: Annotated[str | None, _SET_CHECKED_REV] = None,
) -> None:
    """Set the checked state of some or all tasks in a phase to an absolute value.

    Target either explicit 0-based indices (position-sensitive, so --rev is required
    and paid once for the batch) or --all (rev-free whole-phase set). Value is
    --checked (default) / --unchecked. Idempotent — asserting a known state needs no
    prior read.
    """
    c: AppContext = ctx.obj
    idx = list(indices) if indices else []
    if all_ and idx:
        raise ValidationError("pass either --all or explicit task indices, not both")
    if not all_ and not idx:
        raise ValidationError(
            "give one or more task indices, or --all for the whole phase"
        )
    if idx and rev is None:
        raise ValidationError(
            "--rev is required when targeting explicit task indices (see 'doc rev')"
        )
    reply = c.client.set_tasks_checked(
        c.uid,
        project,
        slug,
        phase_slug,
        checked,
        indices=None if all_ else idx,
        rev=rev,
    )
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")


@app.command()
@handle_errors
def edit(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: Annotated[int, _TASK_INDEX],
    text: Annotated[str, _TEXT],
    rev: Annotated[str, _REV],
) -> None:
    """Replace a task's text (conditional on --rev)."""
    c: AppContext = ctx.obj
    reply = c.client.edit_task(
        c.uid, project, slug, phase_slug, task_index, text, rev=rev
    )
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")


@app.command()
@handle_errors
def rm(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: Annotated[int, _TASK_INDEX],
    rev: Annotated[str, _REV],
) -> None:
    """Remove a task (conditional on --rev)."""
    c: AppContext = ctx.obj
    reply = c.client.remove_task(c.uid, project, slug, phase_slug, task_index, rev=rev)
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")
