---
name: iterate
description: Execute a plan document phase by phase — work the next unfinished phase with the user task by task, checking off boxes, advancing phase pills, and recording learnings in the document as work happens. Takes a plan slug or project. The forward loop of the lifecycle.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent, Read, Edit
---

Drive a plan document through execution, mutating it as reality changes — per `${CLAUDE_PLUGIN_ROOT}/AUTHORING.md`. This is the forward loop: do the work, check off tasks, store learnings in place. (`/plan:review` is the reverse — reconcile after work happened without the document.)

## Resolve & load

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" resolve "<arg>"
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" phases <path>
```

Each → JSON; non-zero exit → relay stderr and stop. `resolve` `kind: ambiguous` → present and ask, don't guess; `kind: project` → use the one `status: active` `type: plan` doc, but if several or none present and ask. Pass the resolved `path` (not the slug — it collides across projects) to `phases`/`touch`/`status`. `phases` returns `{current, tally:{done,total,blocked}, phases:[{ordinal,slug,name,status,note,has_phase_class,tasks:[{line,checked,text}]}]}` — `current` is the slug of the first non-`done` phase (null when all done), each phase has a `status` ∈ `todo|doing|done|blocked`, and `tally` summarizes progress. Read only the current phase's section inline for its prose and exit criteria.

## Work the next phase

- Restate the `current` phase's open tasks to the user.
- Work them **task by task, in conversation** — confirm before each edit, surface commands and output, keep the user in the loop.
- As tasks complete, mutate the document via the writer verbs:
  - check off a task: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" task <path> <phase-slug> <selector> --check` (selector = 1-based index or a substring of the task text);
  - advance the phase: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" set-phase <path> <phase-slug> <status> [--note]` — `doing` when the phase starts, `done` only when exit criteria are met, `blocked` if stuck; `set-phase` bumps the date and auto-completes the doc when the last phase is `done`;
  - add a phase mid-plan: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" add-phase <path> <name> [--after <slug>]`;
  - append learnings to `## Learnings` **as discoveries happen** (format in `templates/plan.md`) — this stays free prose (no verb); for pure-prose edits, still bump the date with `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" touch <path>`.

## Diverge & stop

- If reality diverges from the plan mid-phase, update the prose to match and mark it `!!! note "Revised YYYY-MM-DD"` (ISO date).
- **STOP at exit criteria** for explicit user sign-off before setting the phase to `done` and opening the next phase.
- When the last phase flips to `done`, `set-phase` auto-sets the doc `status: done` (`phases` then reports `current: null`). A zero-phase `phases` array means the plan has no parseable phases — say so and stop; do not propose done.
