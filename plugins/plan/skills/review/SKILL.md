---
name: review
description: Reconcile a saved plan under ~/plans/src/projects against reality — verify which gaps, decisions, and phase tasks were actually implemented, report the drift, and on approval revise the document in place. Can also deep-verify a chosen part of a plan on request. Takes a plan slug. Closes the loop after implementation.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent, Read, Edit
---

Audit a plan document against the current state of the world, then bring the document back in sync — per `${CLAUDE_PLUGIN_ROOT}/AUTHORING.md`. The reverse loop: reconcile after work happened without the document. (`/plan:iterate` is the forward loop that mutates the doc as work happens.) Reconciliation is the default mode; the user may instead ask to strongly verify a specific part of the plan — same report-then-STOP shape, deeper verification.

<!-- This skill uses portable `general-purpose` agent names, not the house scout/investigator roster — a deliberate divergence so it works without those agents installed. -->

## Resolve & extract structure

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" resolve "<arg>"
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" phases <path>
```

Each → JSON; non-zero exit → relay stderr and stop. `resolve` `kind: ambiguous` → present and ask, don't guess; `kind: none` → say no match and run `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" list` to present what exists. Pass the resolved `path` (not the slug — it collides across projects) to `phases`/`touch`/`status`. `phases` supplies every phase, its status (`todo|doing|done|blocked`), and its checkbox states deterministically. Then spawn one `Agent` (`general-purpose`, `haiku`) to read the doc for what the script does not extract: the in-prose status claims (pills `todo`/`doing`/`blocked`) with their surrounding sentence and anchor, the closing gaps/decisions checklist item by item, and every version pin with its stated target.

## 2 — Verify against reality (delegate, sonnet)

For each claim, spawn read-only `general-purpose` (`sonnet`) agents to check what is actually true:

- Do the asserted files/configs/resources exist as the plan specifies?
- Were the `todo` / `doing` / `blocked` phases and unchecked tasks built? Fully or partially?
- Are version pins still current? Check live (web/registry) — never trust training data.

Verdict per claim: **done** / **drifted** (exists but differs — say how) / **still open**.

**Deep verification:** when the user asks to strongly verify part of the plan — or a claim is high-stakes — escalate to an `opus` agent with a targeted brief: challenge the approach itself (correctness, assumptions, missed constraints), not just whether the artifacts exist. Include its findings in the report.

## 3 — Report, then revise on approval

Present the drift as a pipe table (claim · plan said · reality · verdict) and STOP for the user's review. Do not edit before approval.

On approval, revise the doc **in place** — never spawn a `-v2`:

- For **done** items, advance the phase via `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" set-phase <path> <slug> done` and check tasks via `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" task <path> <slug> <selector> --check`; **drifted** / **still open** keep their status.
- Where reality diverged, update the prose to match and mark it `!!! note "Revised YYYY-MM-DD"` (ISO date).
- Append a dated entry to `## Review log {#review-log}` (create if absent): what was verified, what changed, what remains open.
- Bump the date: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" touch <path>`.
- When everything is reconciled (all phases `done`, no open gaps), propose `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" status <path> done`.
