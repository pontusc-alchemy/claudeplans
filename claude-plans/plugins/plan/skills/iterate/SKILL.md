---
name: iterate
description: Execute a plan document phase by phase — work the next unfinished phase with the user task by task, checking off boxes, advancing phase pills, and recording learnings in the document as work happens. Takes a plan slug or project. The forward loop of the lifecycle.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent, Read, Edit
---

Drive a plan document through execution, mutating it as reality changes — per `${CLAUDE_PLUGIN_ROOT}/server/AUTHORING.md`. This is the forward loop: do the work, check off tasks, store learnings in place. (`/plan:review` is the reverse — reconcile after work happened without the document.)

## Resolve the source

Argument is a plan slug or project — resolve like `/plan:prime`: match against `~/plans/src/projects/*/*.md`; a project with multiple active plans → ask. No clear match → `ls` and ask. Don't guess.

## 1 — Load (delegate, haiku)

Spawn one `Agent` (`general-purpose`, `haiku`) for a dense extraction: every `## Phase N` with its pill, its `- [ ]`/`- [x]` checkbox states, and its exit criteria; plus the current Learnings entries.

## 2 — Work the next phase

- Find the **first phase whose pill is not `ok`**. Restate its open tasks to the user.
- Work them **task by task, in conversation** — confirm before each edit, surface commands and output, keep the user in the loop.
- As tasks complete, edit the document in place:
  - flip `- [ ]` → `- [x]`;
  - advance the phase pill: `gap` → `partial` when the phase starts, `partial` → `ok` only when exit criteria are met;
  - append learnings to `## Learnings` **as discoveries happen** (not just at the end), format `- **YYYY-MM-DD (phase N)** — what we learned, what changed because of it.`;
  - bump the frontmatter `date:`.

## 3 — Diverge & stop

- If reality diverges from the plan mid-phase, update the prose to match and mark it `!!! note "Revised YYYY-MM-DD"` (ISO date).
- **STOP at exit criteria** for explicit user sign-off before advancing the pill to `ok` and opening the next phase.

Author edits with the `Edit` tool, never `cat >` heredocs — the guard-sensitive hook scans Bash command content and will false-positive on document text.
