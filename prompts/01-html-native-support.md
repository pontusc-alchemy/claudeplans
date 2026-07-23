# Brief 01 — HTML documents are first-class discoverable content

## INTENDED_GOAL (this session)

A standalone `.html` document placed in the site's served content root is reachable
by a reader **by navigating from the site's home page** (clicking, the same way a
markdown plan is reached) — not only by typing the file's direct URL. Markdown plans
remain reachable the same way. This must hold for the macOS Tier-0 serve flow.

## Measurable success

Observable by a `browser-user` verification dispatch against the running site on this
machine:

- With at least one `.html` document present in the served content root, loading the
  site home page presents a clickable entry that leads to that HTML document. A reader
  who never knew the file's URL can reach it from the home page.
- Activating that entry loads the HTML document and it renders as its own
  self-contained page — its authored styling/content intact, not visually broken.
- At least one markdown plan is still reachable from the home page the same way
  (no regression in markdown discovery).
- All of the above are confirmed in a real browser against the server running on
  this host, not asserted from source inspection alone.

## What success does NOT prescribe

(Implementation freedom — enumerate liberally; do not narrow by inference.)

- The discovery surface: landing card, left-nav entry, list, table, or any other
  clickable path from the home page — any of these satisfies the goal.
- The source of each HTML entry's display metadata (title/date/grouping): parsed from
  the HTML `<title>`/`<h1>`, the filename, the file mtime, a sidecar, or frontmatter.
- The grouping/taxonomy used to organize HTML entries, if any.
- Whether the HTML is left standalone or wrapped by the site theme — provided it
  still renders correctly and is not broken.
- The directory shape the HTML lives in within the served root.
- Whether the outcome is reached via the index hook, the MkDocs config, a plugin, a
  generator step, or any combination — and whether server source is changed at all.

## Hard requirements

(World-constraints only.)

- Any changes live **only** under `plugins/plan/server/`. No other part of the repo
  is modified.
- Markdown-plan discovery that works today must still work after the change.
- Standalone HTML content is served as authored — its on-disk bytes are not rewritten.
- No hardcoded absolute user paths (e.g. `/Users/<name>/…`) introduced into committed
  repo files.
- The macOS Tier-0 flow (`make serve`) remains the supported way to run the site, and
  success is demonstrated by an actual run on this machine.

## Starting friction state

`unidentified` → first dispatch is DIAGNOSE.

Observed symptom to confirm/refute, not a prescribed fix: `.html` files in the served
root are currently retrievable by direct URL but do not appear as a navigable entry
on the home page.

## Out of scope

- Operator-selectable served root via `PLANS_SRC` — that is Brief 02; do not pursue it
  here.
- Restyling/redesigning the HTML documents themselves.
- Authentication, deployment beyond the local Tier-0 serve, or non-macOS tiers.

Anti-clause: "Out of scope" does NOT silently include any particular discovery
mechanism, metadata source, grouping scheme, or the question of whether server source
is modified. Those remain open implementation choices for the orchestrator.

## Project context (inventory, not prescription)

- The site is **MkDocs Material**, served on this macOS host via the Tier-0 path
  `make serve` (foreground, http://127.0.0.1:8001). Relevant files all under
  `plugins/plan/server/`:
  - `Makefile` — targets incl. `config`, `venv`, `serve`, `build`.
  - `mkdocs.yml.tmpl` — MkDocs config template; rendered to
    `~/.config/plans-server/mkdocs.yml` at `make config` time. `docs_dir` currently
    resolves to `~/plans/src`; registers a hook (`gen_index.py`) and `extra_css`.
  - `gen_index.py` — MkDocs `on_page_markdown` hook. Fires only for `index.md`; replaces
    a `<!-- CARDS -->` marker with generated cards. Currently enumerates markdown only
    (`projects/*/*.md`, top-level `*.md`, `projects/*.md`); reads YAML frontmatter for
    title/status/type/date and uses file mtime as the date fallback.
  - `index.md` — the home page; contains the `<!-- CARDS -->` marker. `make config`
    seeds it into the served root if absent.
- Content model today: markdown plans at `projects/<project>/<slug>.md` render to themed
  pages and are carded by the hook. Other files (incl. `.html`) are copied verbatim into
  the built site and served as static assets — reachable by URL, absent from the card
  index, the left nav, and search.
- Real HTML content to exercise the goal exists under the served root already (e.g. a
  `projects/<project>/…*.html` diagram, and a `projects/tmux-agent/master/*.html` set).
  Additional sample diagrams exist at `~/.agent/diagrams/<repo>/<branch>/*.html`.
- A site already exists on disk from prior runs; a stale server may be bound to port
  8001 — the orchestrator owns starting/stopping the server it verifies against.
