# claudeplans (server) — FastAPI service

How a write flows: an `api/` router parses the request → `core.py`
orchestrates it (load → pure transform in `deltas.py` → store via `storage/`)
→ the router then publishes on `events.py` (core itself is event-free
storage orchestration). The event feed fans out to the SSE live view
(`api/view.py`) and the `search.py` index, so anything that must react to a
change subscribes to the feed rather than hooking the write path. `main.py`
is the composition root that wires all of it and fails closed on bad config.

## Root modules (`src/claudeplans/`)

| Module | Intent |
| --- | --- |
| `main.py` | Composition root — app state, middleware, lifespan; new app-level wiring goes here. |
| `__main__.py` | uvicorn entrypoint; drains SSE streams before the graceful-shutdown wait. |
| `config.py` | Env-loaded settings, a dependency-free leaf — new settings land here. |
| `core.py` | The single path every write flows through; routers stay thin, new mutations enter here. |
| `deltas.py` | Pure `Document → Document` transforms used by `core.py` — no I/O. |
| `drift.py` | Non-raising drift linter behind the `warnings[]` in responses. |
| `events.py` | In-process change feed — the single source of "something changed". |
| `cache.py` | Bounded LRU of rendered doc-body HTML, keyed by (doc key, rev). |
| `render.py` | Markdown → sanitized HTML — the one trusted rendering boundary. |
| `templates.py` | Jinja context assembly — templates stay logic-free; compute URLs/flags here. |
| `navigation.py` | Sidebar data: per-user project trees and the user-switcher list. |
| `lineage.py` | Derived lineage view — which plans descend from which research. |
| `projects.py` | Project display-name registry (`projects.json`). |
| `search.py` | In-memory search index, built and kept fresh off the event feed. |

## `api/` — thin routers, one boundary each

| Module | Intent |
| --- | --- |
| `__init__.py` | `install(app)` — the one mount point for every router. |
| `deps.py` | Request-scoped dependencies + the If-Match precondition helper. |
| `envelope.py` | The single success shape: `{data, warnings[]}`. |
| `errors.py` | Domain error → HTTP status, centralized — routers never map errors themselves. |
| `limits.py` | Request body-size guard (middleware). |
| `health.py` | Liveness/readiness probes — no `/v1` prefix, no envelope. |
| `documents.py` / `phases.py` / `tasks.py` / `sections.py` | CRUD routers, thin over `core.py`. |
| `listing.py` | Project/document enumeration for a user. |
| `search.py` | The search route over the in-memory index. |
| `view.py` | Live-view HTML page, its SSE stream, and the project lineage page. |

## `auth/` — swappable identity, pure authz

| Module | Intent |
| --- | --- |
| `provider.py` | The identity seam: who is making this request (noop dev user vs IAP). |
| `identity.py` | Deterministic uid minting for real users; the dev user is fixed, separate. |
| `authz.py` | The pure authorization predicate — no web stack. |
| `registry.py` | File-backed user registry (`users.json`): name → stable uid. |

## `storage/` — the Repository seam

| Module | Intent |
| --- | --- |
| `repository.py` | The async Repository contract every backend implements. |
| `filesystem.py` | Default backend: one JSON file per key under a root dir. |

A new backend implements `repository.py` and must pass
`tests/contract/test_repository_contract.py`.

## `templates/` & `assets/`

Jinja templates are logic-free (all decisions precomputed in `templates.py`);
`_doc_body.html` is the SSE morph payload — its stable element ids are the
delta target map. `assets/` is CSP-strict and self-contained: vendored htmx +
SSE + idiomorph, first-party `ui.js` (sidebar/user-switcher behavior),
`search.js` (command palette), `app.css` (the whole theme, no external URLs).
