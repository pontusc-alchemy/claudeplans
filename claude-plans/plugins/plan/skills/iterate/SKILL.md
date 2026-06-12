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
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" phases <slug>
```

Each → JSON; non-zero exit → relay stderr and stop. `resolve` `kind: ambiguous` → present and ask, don't guess. `phases` returns `{current, phases:[{n,name,anchor,pill,tasks:[{line,checked,text}]}]}` — the current phase and its task states deterministically. Read only the current phase's section inline for its prose and exit criteria.

## Work the next phase

- Restate the `current` phase's open tasks to the user.
- Work them **task by task, in conversation** — confirm before each edit, surface commands and output, keep the user in the loop.
- As tasks complete, edit the document in place:
  - flip `- [ ]` → `- [x]`;
  - advance the phase pill: `gap` → `partial` when the phase starts, `partial` → `ok` only when exit criteria are met;
  - append learnings to `## Learnings` **as discoveries happen** (format in `templates/plan.md`);
  - bump the date: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" touch <slug>`.

## Diverge & stop

- If reality diverges from the plan mid-phase, update the prose to match and mark it `!!! note "Revised YYYY-MM-DD"` (ISO date).
- **STOP at exit criteria** for explicit user sign-off before advancing the pill to `ok` and opening the next phase.
- When every phase pill is `ok` (`phases` reports `current: null`), propose `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" status <slug> done`.
