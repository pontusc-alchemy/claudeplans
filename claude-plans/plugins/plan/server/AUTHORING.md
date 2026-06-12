# Plan / document authoring reference (v2)

How to write Markdown that the plans site (MkDocs + Material) renders at **http://plans.claude**. Applies to every `/plan:*` skill that writes into `~/plans/src/`. The component classes below come from Material plus `assets/extra.css` — use these, don't invent new ones.

## Save & render

- Documents live at `~/plans/src/projects/<project>/<slug>.md`. The **project is the directory name** — never a frontmatter field. The slug is the document's identity within the project — revise in place, never spawn `-v2`. Never write into a project repo or the cwd.
- The `plans-render` MkDocs dev server live-rebuilds on every save → served at **http://plans.claude/projects/<project>/<slug>.html**.
- The landing page is generated at build time, grouped by project, from each document's frontmatter — no manual card edits, and in-doc card grids are not a component.
- Manual build check: `~/.config/plans-server/venv/bin/mkdocs build -f ~/.config/plans-server/mkdocs.yml`.

## Frontmatter contract v2

```yaml
---
title: actions-runner-controller on the IAT Talos cluster
description: Deployment plan, gap analysis & sizing
type: plan
status: active
date: 2026-06-12
tag: talos-infrastructure
---
```

| Field         | Required | Values                        | Used for                                      |
| ------------- | -------- | ----------------------------- | --------------------------------------------- |
| `title`       | yes      | free text                     | page h1, nav, card title                      |
| `description` | yes      | one line                      | card body                                     |
| `type`        | yes      | `research` \| `plan`          | card badge, template selection, lifecycle     |
| `status`      | yes      | `draft` \| `active` \| `done` | card pill, `/plan:prime` doc selection        |
| `date`        | yes      | `YYYY-MM-DD`                  | card date + sort (bump on every revision)     |
| `tag`         | no       | free text                     | extra card tag                                |

Frontmatter is the only metadata source — cards, grouping, and priming all read from it. `date` falls back to the file's mtime if omitted, but always set it explicitly and bump it on every revision.

## Structure

- Do NOT use `# ` headings in the body — the page h1 comes from the frontmatter `title`. One `## Heading` per major section → sidebar TOC entry; `### Heading` for subsections.
- Give sections stable ids for cross-refs: `## Networking {#networking}`.
- Cross-ref with a descriptive anchor link: `[Networking](#networking)`. There is no auto-numbering.

## Document types

Two cornerstones — copy the matching template from `${CLAUDE_PLUGIN_ROOT}/templates/` and fill it; the scaffold is the output contract.

- **`type: research`** (`templates/research.md`) — the full consideration. Sections: executive summary · context & motivation · start state (verbatim: what exists today) · end state · options (pipe table) · references (official docs first, third-party flagged unverified) · gotchas & risks · recommendation · open questions.
- **`type: plan`** (`templates/plan.md`) — references its research doc, never duplicates it. Sections: executive summary · phases · gaps & decisions · learnings · review log.

## Phase conventions (type: plan)

- Each phase is `## Phase N — <name> {#phase-n}` carrying a status pill that advances `gap` → `partial` → `ok`:
  `<span class="pill gap">gap</span>` (not started) · `<span class="pill partial">partial</span>` (in progress) · `<span class="pill ok">ok</span>` (exit criteria met).
- Tasks are a `- [ ]` checklist with exact commands, paths, and version pins; check off as `- [x]` when done.
- Close each phase with explicit **Exit criteria** as a sub-list — the bar for sign-off before the next phase opens.

## Learnings (type: plan)

Append dated entries to `## Learnings {#learnings}` during execution, one place next to the phases that produced them. Entry format:

```
- **YYYY-MM-DD (phase N)** — what we learned, what changed because of it.
```

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
