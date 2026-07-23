# Plan / document authoring reference

How to write Markdown that the plans site (MkDocs + Material) renders at **http://plans.claude**. Applies to every `/plan:*` skill that writes into `~/plans/src/`. The component classes below come from Material plus `assets/extra.css` — use these, don't invent new ones.

- Documents live at `~/plans/src/projects/<project>/<slug>.md` (project = directory name, never a frontmatter field), served at `http://plans.claude/projects/<project>/<slug>.html`. Revise in place, never spawn `-v2`; never write into a repo or the cwd.
- An **optional** branch level is supported: `~/plans/src/projects/<project>/<branch>/<slug>.md` groups docs by branch alongside flat docs (see [Branch level](#branch)).
- Author with the `Write`/`Edit` tools, never `cat >` heredocs — the Bash guard hook scans command content and false-positives on document text.

## Frontmatter

- Six single-line `key: value` fields: `title`, `description`, `type`, `status`, `date` (`tag` optional). Values are single-line — no block scalars, no lists.
- Enums: `type` ∈ `research` | `plan`; `status` ∈ `draft` | `active` | `done`. `date` is `YYYY-MM-DD`, bumped on every revision.
- Enforced by `plan-doc check` — run it after authoring.

Status lifecycle: `draft` = scaffolded / being written; `active` = the live reference (`/plan:prime` selects these); `done` = plans: all phases `ok` and reconciled / research: decision consumed by a plan.

## Structure

- No `# ` h1 in the body — the page h1 comes from the frontmatter `title`. One `## Section {#anchor}` per major section; cross-ref with `[text](#anchor)`.
- The templates under `${CLAUDE_PLUGIN_ROOT}/templates/` are the section contract: copy the matching one and fill it. `templates/plan.md` demonstrates the pill markup, checklist, exit criteria, and learnings entry format — follow it rather than reinventing.

## Branch level {#branch}

A project may group its docs by branch with an optional middle path segment. Both layouts coexist — flat stays first-class, and existing flat docs need no migration.

- Flat: `projects/<project>/<slug>.md`
- Branched: `projects/<project>/<branch>/<slug>.md`

Detection is **structural**, by file-vs-directory:

- A `.md` **file** directly under a project is a flat slug (no branch).
- A **subdirectory** under a project is a branch; the `.md` files inside it are that branch's slugs.

The branch level is capped at **one**: only `projects/<project>/<branch>/<slug>.md` is recognized. Deeper nesting (e.g. `projects/<project>/<branch>/<sub>/<slug>.md`) is NOT treated as a further branch level and such docs are not discovered.

!!! warning "Reserved name: `diagrams/`"
    A subdirectory named `diagrams` is reserved — it holds generated `*.html` and is never treated as a branch (it surfaces as a "Diagrams" link-list, not a doc group). A real git branch literally named `diagrams` would be swallowed by the diagram bucket; avoid it.

## Components

| Need              | Markdown                                                                                                                   |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Status pill       | `<span class="pill ok">decided</span>` · `<span class="pill gap">gap</span>` · `<span class="pill partial">partial</span>` |
| Callout           | `!!! warning "Label"` + body indented 4 spaces (types: `note` `success` `warning` `danger`; collapsible: `???`)            |
| Comparison matrix | standard Markdown pipe table — header row + `--- ` separator row                                                           |
| Inline annotation | `<span class="muted">…</span>` · `<span class="src">…</span>` · `<span class="tag">v1.13</span>`                           |
| Verbatim config   | fenced code block with a language tag (highlighted, copy button)                                                           |

- Inline classed text MUST be a raw HTML `<span>` — Pandoc-style `[text]{.class}` does NOT render here.
- Tables MUST be pipe tables with a header row and a separator row. Never space-separated — that flattens to a broken paragraph.
- Use `!!! warning` / `!!! danger` to flag risky or unverified claims explicitly.
- Write real em-dash characters (`—`) in prose. Literal `---` / `--` are NOT smart-converted here and render as plain hyphens.
- Inter-doc links MUST be relative `.md` links (`[plan](arc-implementation.md)`, `[other project](../other/doc.md)`) — MkDocs rewrites and validates them and they stay portable. Raw-HTML `href`s target the `.html`.

## Build check

`~/.config/plans-server/venv/bin/mkdocs build -f ~/.config/plans-server/mkdocs.yml`.
