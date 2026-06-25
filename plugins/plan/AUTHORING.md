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

### Section

| Field | Type | Notes |
|-------|------|-------|
| `anchor` | str | stable identity key for section ops; must be unique per doc |
| `heading` | str | section heading text |
| `body` | str | plain markdown — by convention no hand-written HTML spans, pills, or admonitions |
| `level` | int 1–6 | heading level; default 2 |

### Phase

| Field | Type | Notes |
|-------|------|-------|
| `slug` | str | stable identity key for phase ops; must be unique per doc |
| `name` | str | human-readable phase name |
| `status` | `todo` \| `doing` \| `done` \| `blocked` | phase lifecycle state |
| `tasks` | list[Task] | ordered task list |

### Task

| Field | Type | Notes |
|-------|------|-------|
| `text` | str | task description |
| `checked` | bool | completion state; default `false` |

## Status lifecycle

- `draft` — being written; not yet a live reference.
- `active` — live reference; a plan under active execution or research in use.
- `done` — all phases completed (plan) or research consumed (research).

## Addressing & discovery

A doc is identified by `(uid, project, slug)`. The slug is the document's identity — renaming requires re-creating the doc. Inter-doc links use the slug (stored in `research_refs`).

The service url and uid come from the CLI config, set once at setup via `claudeplans config set` and readable via `claudeplans config show`. The default fallback is `http://127.0.0.1:8000` with uid `dev`. All values are overridable per-call via `--url`/`--uid` flags or the `CLAUDEPLANS_URL`/`CLAUDEPLANS_UID` env vars — do not hardcode the URL in skills.

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
claudeplans search|schema
```

`doc list` takes `--type research|plan`; `task add` / `section add` take `--at INDEX` for a positional insert (append if omitted). `claudeplans schema` dumps the authoritative machine-readable contract — enums, exit codes, envelope shapes, the `conditional_writes` (which ops need `--rev`), and the `NO_COLOR` env note.

Position-sensitive ops (`task toggle`, `task set-checked`, `task edit`, `task rm`, `phase move`, `section move`, `doc delete`) require `--rev` (the `rev` field from a prior `doc phases`/`doc rev` or a write reply) — the optimistic-concurrency token. Exit 9 means stale rev; re-read and retry. Stable-key ops (`status`, `set`, `add`, rename) are rev-free.

Exit codes: `0` ok · `2` usage error (bad flag/arg — reserved, never a domain error) · `3` forbidden · `4` validation · `5` not-found · `6` transport (service unreachable / bad `--url`) · `9` stale-rev. Every domain error also prints a structured `{"error":<kind>,…}` line to stderr (never a stacktrace); stale-rev carries `current_rev`.

## Server-side invariants (validation → exit 4)

- Research docs carry no phases.
- `primary_research_ref` must be a member of `research_refs`.
- Phase slugs are unique within a document.
- Section anchors are unique within a document.

## Rendering

The service renders HTML from the model using nh3 (scripts, event handlers, and `javascript:` schemes are stripped). By convention, authors should not hand-write HTML spans, pills, or admonitions in section bodies — write plain markdown and let the service render it.

The browsable view URL for a document is obtained via `claudeplans doc view <project> <slug>`. The project lineage page URL is obtained via `claudeplans project view <project>`. Underlying API endpoints (for reference):

```
GET /v1/users/{uid}/projects/{project}/docs/{slug}/view
GET /v1/users/{uid}/projects/{project}/
GET /v1/users/{uid}/projects/{project}/search
```
