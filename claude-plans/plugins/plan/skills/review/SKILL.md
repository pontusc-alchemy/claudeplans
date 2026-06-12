---
name: review
description: Reconcile a saved plan under ~/plans/src/projects against reality — verify which gaps, decisions, and phase tasks were actually implemented, report the drift, and on approval revise the document in place. Takes a plan slug. Closes the loop after implementation.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent, Read, Edit
---

Audit a plan document against the current state of the world, then bring the document back in sync — per `${CLAUDE_PLUGIN_ROOT}/server/AUTHORING.md`. The reverse loop: reconcile after work happened without the document. (`/plan:iterate` is the forward loop that mutates the doc as work happens.)

## Input

Match the argument against `~/plans/src/projects/*/*.md` — same rule as `/plan:prime`: no clear single match → `ls ~/plans/src/projects/*/*.md` and ask. Don't guess.

## 1 — Extract claims (delegate, haiku)

Spawn one `Agent` (`general-purpose`, `haiku`) to read the doc and return verbatim:

- every `<span class="pill gap">` / `<span class="pill partial">` item with its surrounding sentence and section anchor;
- every phase checklist item (`- [ ]` / `- [x]`) and its stated target;
- every roadmap step (commands, file paths, config blocks) and its stated target;
- every version pin;
- the closing gaps/decisions checklist, item by item.

## 2 — Verify against reality (delegate, sonnet)

For each claim, spawn read-only `general-purpose` (`sonnet`) agents to check what is actually true:

- Do the asserted files/configs/resources exist as the plan specifies?
- Were the `gap` / `partial` items and unchecked tasks built? Fully or partially?
- Are version pins still current? Check live (web/registry) — never trust training data.

Verdict per claim: **done** / **drifted** (exists but differs — say how) / **still open**.

## 3 — Report, then revise on approval

Present the drift as a pipe table (claim · plan said · reality · verdict) and STOP for the user's review. Do not edit before approval.

On approval, revise the doc **in place** — never spawn a `-v2`:

- Flip pills for **done** items: `pill gap` / `pill partial` → `pill ok`; check off completed checklist items and advance phase pills. **drifted** / **still open** items keep their pill.
- Where reality diverged, update the prose to match and mark it `!!! note "Revised YYYY-MM-DD"` (ISO date).
- Append a dated entry to `## Review log {#review-log}` (create if absent): what was verified, what changed, what remains open.
- Bump the frontmatter `date:` — the landing-page card date is generated from it.
