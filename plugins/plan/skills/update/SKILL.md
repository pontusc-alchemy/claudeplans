---
name: update
description: Make a targeted revision to a saved plan or research document under ~/plans/src/projects — edit a section, option, version pin, gap, or frontmatter field on request, then bump the date and validate. Takes a doc slug or project plus the change to make. The direct-edit loop of the lifecycle.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Read, Edit
---

Apply an intent-driven revision to a saved document — per `${CLAUDE_PLUGIN_ROOT}/AUTHORING.md`. This is the direct loop: change content because the user asked, when no implementation or audit is happening. (`/plan:iterate` is the forward loop that edits as work happens; `/plan:review` is the reverse loop that reconciles against reality.) Works on both `research` and `plan` docs.

## Resolve

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" resolve "<arg>"
```

→ JSON `{kind, docs}`; non-zero exit → relay stderr and stop. `kind: ambiguous` → present and ask, don't guess; `kind: none` → say no match and run `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" list` to present what exists. Pass the resolved `path` (not the slug — it collides across projects) to `touch`/`status`/`check`. Read only the section the change targets inline.

## Revise

- Confirm the change with the user before editing — restate what will change and where.
- Edit in place with `Edit`/`Write` per AUTHORING (raw `<span>` pills, single-line frontmatter, real em-dashes, relative `.md` links). Never spawn a `-v2`.
- Body changes: revise the targeted section, option, pin, or gap directly. For a plan's phase status use `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" set-phase <path> <slug> <status>` (`todo|doing|done|blocked`) and toggle phase tasks with `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" task <path> <slug> <selector> --check|--uncheck` — don't hand-edit phase pills or checkboxes. Decision pills outside phases (e.g. items under `## Gaps & decisions`) remain hand-edited per AUTHORING.
- Frontmatter changes: `title`/`description`/`tag`/`type` are single-line edits (the `---` block). For `status`, prefer `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" status <path> <state>` over hand-editing.
- Structural moves (rename/move/delete) are out of scope — they change the slug and break inter-doc links; do those by hand and re-run `check`.

## Bump & validate

- Bump the date: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" touch <path>`.
- Validate: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" check <path>` — non-zero exit → relay stderr and fix before finishing.
- If the edit closed all open gaps or, conversely, reopened decided work, propose the matching `status` flip (`done` / `active`).
