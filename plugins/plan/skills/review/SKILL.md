---
name: review
description: Reconcile a saved plan in the claudeplans service against reality — verify which gaps, decisions, and phase tasks were actually implemented, report the drift, and on approval revise the document in place via the CLI. Can also deep-verify a chosen part of a plan on request. Takes a plan project and slug. Closes the loop after implementation.
user-invocable: true
model-invocable: true
allowed-tools: Bash, Agent
---

Audit a plan document against the current state of the world, then bring the document back in sync via the claudeplans CLI. The reverse loop: reconcile after work happened without the document. (`/plan:iterate` is the forward loop that mutates the doc as work happens.) Reconciliation is the default mode; the user may instead ask to strongly verify a specific part of the plan — same report-then-STOP shape, deeper verification.

<!-- This skill uses portable `general-purpose` agent names, not the house scout/investigator roster — a deliberate divergence so it works without those agents installed. -->

## 1 — Extract structure

Arguments must carry both `<project>` and `<slug>` — there is no fuzzy resolve. For project-wide discovery: list projects with `claudeplans project list`, list a project's documents with `claudeplans doc list <project>` (both return JSON). The lineage page is the human browser view — open it with `claudeplans project view <project>` which prints its URL. (The search endpoint requires `?q=<term>` and performs keyword search, not enumeration.)

```shell
claudeplans doc phases "<project>" "<slug>"
```

→ JSON `{rev, phases:[{slug, name, status, tasks:[{text, checked}]}], warnings}`; hold `rev`. Then read prose using projections — `--phase` returns a phase with its `intro`/`exit_criteria`/`notes`; `--section` returns a section body:

```shell
claudeplans doc get "<project>" "<slug>" --section "<anchor>"
claudeplans doc get "<project>" "<slug>" --phase "<phase-slug>"
claudeplans doc get "<project>" "<slug>" --fields "title,description,status,research_refs"
```

Non-zero exit on any call → relay stderr and stop.

Spawn one `Agent` (`general-purpose`, `haiku`) to process the full structure output and return: the in-prose status claims with their surrounding context, the open gaps/decisions item by item, and every version pin with its stated target.

Instruct every delegated agent (here and in step 2) to return findings only and never call the `claudeplans` CLI for any write — create, modify, or delete — the CLI is on PATH, so an unbriefed agent may author its own; all revisions happen in the main thread on approval.

## 2 — Verify against reality (delegate, sonnet)

For each claim, spawn read-only `general-purpose` (`sonnet`) agents to check what is actually true:

- Do the asserted files/configs/resources exist as the plan specifies?
- Plan carries a module map (`module-map` / `mod-*` sections)? Verify **shape**,
  not just existence: diff the implemented interfaces, dependencies, artifacts,
  and side effects against each card's Requires/Provides. A **drifted** verdict
  names the contract line that diverged.
- Were the `todo` / `doing` / `blocked` phases and unchecked tasks built? Fully or partially?
- Are version pins still current? Check live (web/registry) — never trust training data.

Verdict per claim: **done** / **drifted** (exists but differs — say how) / **still open**.

**Deep verification:** when the user asks to strongly verify part of the plan — or a claim is high-stakes — escalate to an `opus` agent with a targeted brief: challenge the approach itself (correctness, assumptions, missed constraints), not just whether the artifacts exist. Include its findings in the report.

## 3 — Report, then revise on approval

Present the drift as a pipe table (claim · plan said · reality · verdict) and STOP for the user's review. Do not edit before approval.

On approval, revise the doc **in place** — never create a new slug or version:

- For **done** items, advance the phase (re-read `doc phases` to refresh `rev` first; if a write exits `9`, reuse the `current_rev` it prints and retry). When an entire phase reconciles as complete, `phase complete` checks every task and sets it done in one rev-free call; otherwise advance granularly:
  ```shell
  claudeplans phase complete "<project>" "<slug>" "<phase-slug>"       # whole phase, rev-free
  claudeplans phase set-status "<project>" "<slug>" "<phase-slug>" done
  claudeplans task set-checked "<project>" "<slug>" "<phase-slug>" --all   # rev-free
  claudeplans task toggle "<project>" "<slug>" "<phase-slug>" <index> --rev <rev>
  ```
- **Drifted** / **still open** items keep their status.
- Where reality diverged, update phase prose via `phase set` (`--intro`/`--exit-criteria`/`--notes`; revision cards go in `--notes`), or a section body via `section set` / `section patch` — plain markdown, no HTML spans or pills:
  ```shell
  claudeplans phase set "<project>" "<slug>" "<phase-slug>" --notes-file - <<'EOF'
  !!! note "Revised"
      Block form required: type + quoted title, body indented 4 spaces.
  EOF
  claudeplans section set "<project>" "<slug>" "<anchor>" --body "<updated markdown>"
  claudeplans section patch "<project>" "<slug>" "<anchor>" --merge-patch '{"body":"<updated>"}'
  ```
  Contract drift reconciles into the module card itself (`section set` on `mod-<name>`) with the decision recorded in the owner phase's `--notes` — never into phase prose alone; name the amended cards in the review-log entry.
- Append a dated entry to a `review-log` section (create if absent):
  ```shell
  # Create if absent:
  claudeplans section add "<project>" "<slug>" "review-log" "Review log" --level 2
  # Append via set (replace body with prior content + new entry):
  claudeplans section set "<project>" "<slug>" "review-log" --body "<full updated body>"
  ```
  Entry format (plain markdown): `## YYYY-MM-DD — what was verified, what changed, what remains open`.
- When everything is reconciled (all phases `done`, no open gaps), propose:
  ```shell
  claudeplans doc status "<project>" "<slug>" done
  ```
