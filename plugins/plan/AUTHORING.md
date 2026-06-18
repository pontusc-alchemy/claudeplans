# Plan / document authoring reference

How to write Markdown that the plans site (MkDocs + Material) renders at **http://plans.claude**. Applies to every `/plan:*` skill that writes into `~/plans/src/`. The component classes below come from Material plus `assets/extra.css` — use these, don't invent new ones.

- Documents live at `~/plans/src/projects/<project>/<slug>.md` (project = directory name, never a frontmatter field), served at `http://plans.claude/projects/<project>/<slug>.html`. Revise in place, never spawn `-v2`; never write into a repo or the cwd.
- Author with the `Write`/`Edit` tools, never `cat >` heredocs — the Bash guard hook scans command content and false-positives on document text.

## Frontmatter

- Six single-line `key: value` fields: `title`, `description`, `type`, `status`, `date` (`tag` optional). Values are single-line — no block scalars, no lists.
- Enums: `type` ∈ `research` | `plan`; `status` ∈ `draft` | `active` | `done`. `date` is `YYYY-MM-DD`, bumped on every revision.
- Enforced by `plan-doc check` — run it after authoring.

Status lifecycle: `draft` = scaffolded / being written; `active` = the live reference (`/plan:prime` selects these); `done` = plans: all phases `done` and reconciled / research: decision consumed by a plan.

## Structure

- No `# ` h1 in the body — the page h1 comes from the frontmatter `title`. One `## Section {#anchor}` per major section; cross-ref with `[text](#anchor)`.
- The templates under `${CLAUDE_PLUGIN_ROOT}/templates/` are the section contract: copy the matching one and fill it. `templates/plan.md` demonstrates the phase heading, machine-managed status line, checklist, exit criteria, and learnings entry format — follow it rather than reinventing.

## Document types

- **research** docs gather *what's possible* — options, trade-offs, a recommendation. Prose, pipe tables, and admonitions; a decision pill (`<span class="pill done">decided</span>`) is fine, but **no `.phase` headings or phase tracker**. Use `templates/research.md`.
- **plan** docs decide *what to do* — ordered phases the work executes against. Use `templates/plan.md`. A plan **links the research it consumes via a relative `.md` link in its intro** — there is no frontmatter link field; cite by prose link, never copy the research forward.
- `plan-doc check` is type-aware and *warns* (never errors): a `plan` with no phases, or a `research` doc carrying plan structure (pills / `.phase` headings), is flagged for attention.

## Phases (plan docs only)

- A phase is a `## <name> {#slug .phase}` heading immediately followed by a machine-managed status line: `<span class="pill todo">todo</span>`, optionally with a sibling note `<span class="note">short note</span>`.
- Identity is the stable `{#slug}`; the rendered "Phase N — " ordinal comes from document position. The phase tracker (progress bar + per-phase list) is generated automatically at the top of the page — **do not hand-write a phase/status table**.
- Phase status enum: `todo | doing | done | blocked`. `blocked` is parked, not progress — it is excluded from the done count and vetoes auto-completion.
- Status is **machine-managed — never hand-edit the pill or the checkboxes**. Use the writers:
  - `plan-doc set-phase <path> <slug> <status> [--note]` — advance a phase (auto-sets the doc to `done` when the last phase is `done`, none `blocked`);
  - `plan-doc task <path> <slug> <selector> --check|--uncheck` — toggle a task (selector = index or substring);
  - `plan-doc add-phase <path> <name> [--after <slug>]` — insert a phase.
- Reference a phase in prose by its slug link `[name](#slug)`, never literal "Phase N" (check warns on it). Decision pills *outside* phases (e.g. under `## Gaps & decisions`) use the same enum but are hand-edited.

## Components

| Need              | Markdown                                                                                                                   |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Status pill       | `<span class="pill todo">todo</span>` · `<span class="pill doing">doing</span>` · `<span class="pill done">done</span>` · `<span class="pill blocked">blocked</span>` (phase status is machine-managed — see Phases) |
| Callout           | `!!! warning "Label"` + body indented 4 spaces (types: `note` `success` `warning` `danger`; collapsible: `???`)            |
| Comparison matrix | standard Markdown pipe table — header row + `--- ` separator row                                                           |
| Inline annotation | `<span class="muted">…</span>` · `<span class="src">…</span>` · `<span class="tag">v1.13</span>`                           |
| Verbatim config   | fenced code block with a language tag (highlighted, copy button)                                                           |

- Inline classed text MUST be a raw HTML `<span>` — Pandoc-style `[text]{.class}` does NOT render here.
- Tables MUST be pipe tables with a header row and a separator row. Never space-separated — that flattens to a broken paragraph.
- Use `!!! warning` / `!!! danger` to flag risky or unverified claims explicitly.
- Write real em-dash characters (`—`) in prose. Literal `---` / `--` are NOT smart-converted here and render as plain hyphens.
- Inter-doc links MUST be relative `.md` links (`[plan](arc-implementation.md)`, `[other project](../other/doc.md)`) — MkDocs rewrites and validates them and they stay portable. Raw-HTML `href`s target the `.html`.

## Drift & autofix

`plan-doc check <path>` warns (never blocks) on format drift — legacy pills, `## Phase N` headings, manual phase tables, Pandoc `[text]{.class}` spans, prose `--`/`---`, and dead `#anchor` links — and prints a restructure checklist. Mechanical drift is auto-fixable: `plan-doc fix <path>` previews a diff, `plan-doc fix <path> --write` applies it (legacy pill enum, `checklist`→`gaps` anchor, Pandoc spans, prose dashes). Structural moves (numeric headings, manual tables) are left for the manual restructure.

## Build check

`~/.config/plans-server/venv/bin/mkdocs build -f ~/.config/plans-server/mkdocs.yml`.
