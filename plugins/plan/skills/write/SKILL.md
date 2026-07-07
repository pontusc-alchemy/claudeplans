---
name: write
description: Author an actionable implementation plan as a structured document in the claudeplans service (CLI + live HTML view). Turns a discussion — or an existing research document — into ordered, phased implementation steps with decisions and learnings.
user-invocable: true
model-invocable: true
allowed-tools: Bash, Agent
---

Produce an **actionable** implementation plan in the claudeplans service via the CLI. This is the action cornerstone: where `/plan:research` gathers _what's possible_, `/plan:write` decides _what to do_ and _how_.

<!-- This skill uses portable `general-purpose` agent names, not the house scout/investigator roster — a deliberate divergence so it works without those agents installed. -->

Argument: `<project> [research-slug]`.

## 0 — Scaffold

Generate a URL-safe slug for the plan title (kebab-case, ≤40 chars). Create the document:

```shell
claudeplans doc create "<project>" --type plan --slug "<slug>" --title "<plan title>"
```

→ the slim create reply `{slug, type, rev, warnings}` (pass `--full`/`-v` for the whole `{rev, data, warnings}` envelope); non-zero exit → relay stderr and stop. The project is created implicitly on the first doc and there is no new-project warning — so if this is a NEW project (not in `claudeplans project list`), **confirm the project name with the user first**: both the URL-safe slug and the intended display name. Keep the plan `--title` short and navigable (a few words); the descriptive detail belongs in the doc's summary, not the title. After creating a new project's first doc, set its display name: `claudeplans project set-name "<project>" "<Display Name>"`. The shell form also accepts `--status`/`--description`/`--date` in the same call (e.g. reconstructing a completed plan with `--status done`), avoiding a follow-up `doc set`/`set-status`. Run `claudeplans schema` for the authoritative flag map, enums, and exit codes; `claudeplans doc create --help` documents the `--from-json` body shape.

## Input — where the plan comes from

- **From a research doc:** given `research-slug`, delegate a Haiku `Agent` to run `claudeplans doc get "<project>" "<research-slug>"` and return its sections, options, recommendations, links, and constraints. Convert those into decisions and phases — link the consumed research via:
  ```shell
  claudeplans doc link "<project>" "<plan-slug>" "<research-slug>" --primary
  ```
- **From the conversation:** structure the plan we've worked out.
- **From the repo:** any codebase context-gathering goes to `general-purpose` agents — never read large files in the main thread. Instruct these agents to return findings only and never call the `claudeplans` CLI for any write — create, modify, or delete (the CLI is on PATH — an unbriefed agent may author its own); all writes happen in the main thread.

Build the complete doc — all phases, tasks, and prose sections — via the CLI, then point the user to the rendered view (`claudeplans doc view`) to review; do not preview the structure in chat (it is easier to read in the browser). Lead with an "executive-summary" section answering the user's explicit questions, each referencing its phase. Pause for explicit user approval only at the status flip (see "On approval" below).

## Build the structure

For the initial build you have two paths. If the full plan structure is already settled, **skip the plain `doc create` above** and issue that create as a single `--from-json -` call carrying the entire body — sections plus phases-with-tasks (there is no per-phase or per-task bulk verb, so this is the one-call scaffold path; `claudeplans doc create --help` shows the body shape, and validate the JSON before piping since one bad field rejects the whole scaffold). Otherwise — building interactively, or the structure still emerging — run the plain create above and extend it with the per-item `add` verbs below.

Add phases and tasks:

```shell
claudeplans phase add "<project>" "<slug>" "<phase-slug>" "<Phase Name>"
claudeplans task add "<project>" "<slug>" "<phase-slug>" "Task description"
```

`phase add` accepts the same prose flag spellings `phase set` does — `--intro`/`--exit-criteria`/`--notes` (inline) and `--intro-file`/`--exit-criteria-file`/`--notes-file` (a file path, or `-` for stdin) — so a phase and its intro / exit-criteria / notes land in one call instead of an `add` then a follow-up `set`. Note the omit-semantics differ: on `add` (a create) omitted prose defaults to **empty**, whereas on `set` omitted leaves the field unchanged and `''` clears it.

`task add --checked` creates a task already-checked in one rev-free call — use it when reconstructing an already-completed plan so you skip the per-task `toggle --rev` loop (read rev → toggle → repeat). The default is unchecked.

Add prose sections:

```shell
claudeplans section add "<project>" "<slug>" "<anchor>" "<Heading>" --body "<markdown>" --level 2
```

`--body` takes inline text or `--body-file <path>` (`-` for stdin), mirroring the phase prose flags — reach for the file form for multi-line markdown to sidestep shell-quoting pain. `section set` accepts the same pair.

Section bodies are **plain markdown** — do not write HTML spans, pills, or admonitions; the service renders and sanitizes.

## Phase decomposition

The default shape for carving work into phases — deviate with judgment (a migration or a spike may not decompose this way), but note why in the executive summary:

- **Boundaries first.** Decide the modules/components and the seams between them before writing any phase; the shape contracts below hang off those boundaries.
- **One phase = one independently verifiable unit.** Each phase delivers a piece provable on its own, and its `exit_criteria` **is** that proof — a runnable check (tests pass, `terraform plan` clean, a functional probe against the deployed unit), not "code written".
- **Front-load assumption checks.** The first phase verifies whatever the rest of the plan hangs on (module capabilities, live-system facts, access) so a wrong assumption dies in phase 1, not phase 6.
- **Integrate last, explicitly.** Wiring proven pieces together is its own phase with end-to-end exit criteria — never smeared across the build phases.

## Module map

Plans that introduce or reshape more than one code unit carry a **module map** —
the wiring diagram the phases build against. Skip it (and say so in the executive
summary) for single-module plans, config-only changes, or spikes; the per-phase
Task shape below then carries the load alone. Card format and anchors are
specified in `${CLAUDE_PLUGIN_ROOT}/AUTHORING.md` § Document conventions.

- **One `module-map` section** (anchor `module-map`, after the executive
  summary): the module list (name → owner phase) and the dependency edges —
  `A → B: what crosses the seam` — plus the end-to-end proof the integration
  phase must run. Wiring only; contracts live in the cards.
- **One card per module** (anchor `mod-<name>`, level 3): **Purpose** ·
  **Requires** (inputs, config, upstream `§ mod-x`, pinned external deps) ·
  **Provides** (interface skeletons — names + signatures + load-bearing
  fields, artifacts, side effects) · **Verification** (the runnable check
  proving Provides holds) · **Owner** (`<phase-slug>`). The card is the
  single source of truth for that module's shape.
- **Phases point, never copy.** Phase intros reference cards
  (`Builds § mod-parser`; `Wires § mod-parser → § mod-store`) — a contract
  stated twice is a contract that drifts. The integration phase's intro is the
  edge list; its `exit_criteria` is the end-to-end proof from `module-map`.
- **Every Provides line is somebody's Requires** — an output no module or
  exit criterion consumes is scope creep; a Requires nothing provides is a
  missing phase. Check both directions before the status flip.

## Task shape & constraints

Tasks state intent **plus the decisions the implementer would otherwise guess** — a task that leaves structure open gets implemented "correctly" in the wrong shape. When the plan carries a module map, file trees, interfaces, and placement live in the module cards — phase prose points (`Builds § mod-parser`), never restates. For map-less code-heavy phases, pin the shape in the phase prose (`--intro`/`--notes`), not crammed into task text:

- **File tree** of the files the phase creates or reshapes — a short indented list is enough.
- **Public interfaces**: names and signatures (params, returns) of the functions/classes/CLI verbs the phase introduces. Skeletons only — signatures and load-bearing fields, never full implementations; verbatim shapes stay in the research doc (no research doc? give them a dedicated section in the plan itself).
- **Placement & naming**: which module/package each piece lands in, plus any naming decisions that must hold across tasks.
- **Canonical-pattern pointers**: where the implementer finds the intended idiom, chosen by what the phase touches — code phases point at API/library docs and an in-repo file to mirror; infra phases point at provider docs or module source. Reference research-doc material by anchor (`see research <research-slug> § <anchor>`) so it is resolvable, not "see the research doc".

Keep tasks single-action. When a task is judgment-heavy, embed its acceptance criterion in the task text ("…; done when X") rather than relying on the phase-level exit criteria alone.

## On approval

Once the user approves the plan, flip status:

```shell
claudeplans doc status "<project>" "<slug>" active
```

When the plan was built from a research doc, its decision is now consumed — propose:

```shell
claudeplans doc status "<project>" "<research-slug>" done
```

Get the browsable view URL with `claudeplans doc view "<project>" "<slug>"`.
