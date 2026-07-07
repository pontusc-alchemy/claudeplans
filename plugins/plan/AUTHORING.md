# claudeplans Authoring Reference

The source of truth for all model fields is `packages/contracts/src/claudeplans_contracts/models.py`.

## Document model

A `Document` is identified by `(owner_id, project, slug)` — all three are required. There is no fuzzy resolve; skills must pass `project` and `slug` explicitly, and enumerate with `claudeplans project list` / `claudeplans doc list <project>` when a slug is unknown.

Fields:

| Field | Type | Notes |
|-------|------|-------|
| `type` | `plan` \| `research` | immutable after creation |
| `project` | str | key segment — URL-safe slug chars only |
| `slug` | str | key segment — URL-safe slug chars only |
| `title` | str | human-readable title |
| `owner_id` | str | user identity (dev stack default: `dev`) |
| `status` | `draft` \| `active` \| `done` | lifecycle state |
| `schema_version` | int | currently `1`; set by the service |
| `date` | str \| null | ISO date, optional |
| `description` | str \| null | short summary, optional |
| `frontmatter` | dict | free-form JSON-serializable metadata escape hatch |
| `research_refs` | list[str] | slugs of linked research docs |
| `primary_research_ref` | str \| null | must be one of `research_refs` |
| `sections` | list[Section] | ordered prose sections |
| `phases` | list[Phase] | ordered phases (plan docs only) |

Keep `title` short and navigable — it is the label in every sidebar and lineage list, so a few words, not a full sentence. Put the descriptive detail in the document's executive summary / first section, not the title.

## Projects

The `project` key segment in `(owner_id, project, slug)` must use URL-safe chars only (`[A-Za-z0-9_-]`), lowercase-kebab, kept short and stable. It appears in every URL and is the namespace identity; renaming a project means re-creating its docs.

A project also carries an optional **display name** — free-form text shown in the sidebar and as the lineage/landing page title (e.g. slug `arch-decisions` → "Architecture Decisions"). The display name does NOT affect routing or identity. Set or change it with:

```
claudeplans project set-name <project> "<Display Name>"
```

`claudeplans project list` reports it as the `name` field (null when unset; the UI falls back to the slug).

**Confirm the project name with the user before creating a new project.** A project is created implicitly on the first `doc create` and there is no new-project warning, so a typo silently starts a new namespace. Before the first doc in a project not already listed by `claudeplans project list`, confirm the slug AND the intended display name with the user.

### Section

| Field | Type | Notes |
|-------|------|-------|
| `anchor` | str | stable identity key for section ops; must be unique per doc |
| `heading` | str | section heading text |
| `body` | str | plain markdown — no hand-written HTML spans or pills |
| `level` | int 1–6 | heading level; default 2 |
| `placement` | `lead` \| `trail` | render bucket: `lead` renders before the phase group, `trail` after; default `lead` |

### Phase

| Field | Type | Notes |
|-------|------|-------|
| `slug` | str | stable identity key for phase ops; must be unique per doc |
| `name` | str | human-readable phase name |
| `status` | `todo` \| `doing` \| `done` \| `blocked` | phase lifecycle state |
| `intro` | str | intro prose (markdown), rendered above the checklist; set at creation via `phase add --intro` or later via `phase set --intro` |
| `tasks` | list[Task] | ordered task list |
| `exit_criteria` | str | exit-criteria prose (markdown), rendered below the checklist; set at creation via `phase add --exit-criteria` or later via `phase set --exit-criteria` |
| `notes` | str | phase notes / revision cards (markdown — `!!!`/`???` admonitions live here); set at creation via `phase add --notes` or later via `phase set --notes` |

### Task

| Field | Type | Notes |
|-------|------|-------|
| `text` | str | task description |
| `checked` | bool | completion state; default `false`; settable at creation via `task add --checked` |

## Status lifecycle

- `draft` — being written; not yet a live reference.
- `active` — live reference; a plan under active execution or research in use.
- `done` — all phases completed (plan) or research consumed (research).

## Addressing & discovery

A doc is identified by `(uid, project, slug)`. The slug is the document's identity — renaming requires re-creating the doc. Inter-doc links use the slug (stored in `research_refs`).

The service url and uid come from the CLI config, set once at setup via `claudeplans config set` and readable via `claudeplans config show`. The default fallback is `http://127.0.0.1:8000` with uid `dev`. All values are overridable per-call via `--url`/`--uid` flags or the `CLAUDEPLANS_URL`/`CLAUDEPLANS_UID` env vars — do not hardcode the URL in skills. To confirm where the CLI is pointed and whether that server is reachable before issuing a write, run `claudeplans doctor` → JSON `{url, uid, reachable, version?, storage_backend?, auth_mode?, detail?}` (always exits 0; a transport failure or mis-targeted config surfaces as `reachable: false`).

Discovery of what exists is done via the CLI:
- `claudeplans project list` — lists all projects (JSON)
- `claudeplans doc list <project>` — lists a project's documents (JSON)

The lineage page is the human browser view of a project; get its URL with `claudeplans project view <project>`. The browsable view URL for an individual document is obtained via `claudeplans doc view <project> <slug>`.

## CLI surface

All mutations go through the `claudeplans` CLI — state is never hand-edited:

```
claudeplans config set|show
claudeplans project list|lineage|view
claudeplans doc create|get|delete|status|set-status|set|phases|link|unlink|list|rev|view
claudeplans phase add|set|set-status|move|rm
claudeplans task add|toggle|set-checked|edit|rm
claudeplans section add|set|patch|move|rm
claudeplans search|schema|doctor
```

`doc list` takes `--type research|plan`; `task add` / `section add` take `--at INDEX` for a positional insert (append if omitted). `task add` also takes `--checked` to create a task already-checked in one rev-free call (handy when authoring an already-completed plan — skips the per-task `toggle --rev` loop). `doc create`'s shell form takes `--status`/`--description`/`--date` so a described/active/done doc lands in one call (or pass the whole body, including nested sections and phases-with-tasks, via `--from-json` — this is the bulk authoring path; there is no per-task or per-phase bulk-add verb, so to add many tasks at once scaffold them through `--from-json`). `claudeplans schema` dumps the authoritative machine-readable contract — enums, exit codes, envelope shapes, the `conditional_writes` (which ops need `--rev`), the `NO_COLOR` env note, and a per-command flag map. `command_flags` is keyed by fully-qualified command name (`"task add"`, or the bare name for flat commands) → each flag's `{opts, kind: argument|option, required, type}` (plus `secondary_opts` for toggles like `--checked/--unchecked`); `global_flags` lists the root options (`--url`/`--uid`/`--full`), which are passed *before* the subcommand. So an agent can read flag spellings and value types straight from `schema` without consulting this file.

Position-sensitive ops (`task toggle`, `task edit`, `task rm`, `phase move`, `section move`, `doc delete`) require `--rev` (the `rev` field from a prior `doc phases`/`doc rev` or a write reply) — the optimistic-concurrency token. `doc rev` prints the bare rev token by default (the envelope is behind `--json`/`--full`), so it composes directly as `--rev "$(claudeplans doc rev <project> <slug>)"`. `task set-checked` requires `--rev` only for its explicit-index form; its `--all` form is rev-free, as is `phase complete`. Exit 9 means stale rev; re-read and retry. Stable-key ops (`status`, `set`, `add`, rename) are rev-free.

Exit codes: `0` ok · `2` usage error (bad flag/arg — reserved, never a domain error) · `3` forbidden · `4` validation · `5` not-found · `6` transport (service unreachable / bad `--url`) · `9` stale-rev. Every domain error also prints a structured `{"error":<kind>,…}` line to stderr (never a stacktrace); stale-rev carries `current_rev`. A malformed `--rev` (not a decimal integer string) is rejected as `invalid_rev` (exit 4) before any concurrency check — do not retry it; fix the value instead.

## Server-side invariants (validation → exit 4)

- Research docs carry no phases.
- `primary_research_ref` must be a member of `research_refs`.
- Phase slugs are unique within a document.
- Section anchors are unique within a document.

## Rendering

The service renders HTML from the model using nh3 (scripts, event handlers, and `javascript:` schemes are stripped). By convention, authors should not hand-write HTML spans or status pills — write plain markdown and let the service render it. Revision/decision admonition cards (`!!!`/`???`) belong in a phase's `notes` field, not in section bodies.

The browsable view URL for a document is obtained via `claudeplans doc view <project> <slug>`. The project lineage page URL is obtained via `claudeplans project view <project>`. Underlying API endpoints (for reference):

```
GET /v1/users/{uid}/projects/{project}/docs/{slug}/view
GET /v1/users/{uid}/projects/{project}/
GET /v1/users/{uid}/projects/{project}/search
```

## Document conventions

Reserved section anchors the skills read and write by name:

- `module-map` — plan wiring: module list (name → owner phase), dependency
  edges (`A → B: what crosses the seam`), the integration phase's end-to-end
  proof. Wiring only.
- `mod-<name>` — one card per module, level 3, the source of truth for its
  contract: **Purpose** · **Requires** (inputs, config, upstream `§ mod-x`,
  pinned deps) · **Provides** (interface skeletons, artifacts, side effects) ·
  **Verification** (runnable proof of Provides) · **Owner** (phase slug).
- `learnings` — discoveries recorded during `/plan:iterate`.
- `review-log` — dated reconciliation entries from `/plan:review`.

In-doc pointers are spelled `§ <anchor>`; cross-doc pointers
`see research <slug> § <anchor>`. Contracts are stated once, in the card —
phases and tasks point.
