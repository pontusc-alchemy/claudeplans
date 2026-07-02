---
name: iterate
description: Execute a plan document phase by phase — work the next unfinished phase with the user task by task, checking off boxes, advancing phase status, and recording learnings in the document as work happens. Takes a plan slug or project. The forward loop of the lifecycle.
user-invocable: true
model-invocable: true
allowed-tools: Bash, Agent
---

Drive a plan document through execution, mutating it via the claudeplans CLI as reality changes. This is the forward loop: do the work, check off tasks, store learnings in place. (`/plan:review` is the reverse — reconcile after work happened without the document.)

## Load

```shell
claudeplans doc phases "<project>" "<slug>"
```

→ JSON `{rev, phases:[{slug, name, status, tasks:[{text, checked}]}], warnings}`; non-zero exit → relay stderr and stop. The `current` phase is the first entry whose `status` is not `done` — compute this from the list. Hold the `rev` value — it is required for every position-sensitive write. The current phase's prose (`intro` / `exit_criteria` / `notes`) lives in its own fields — read them with `claudeplans doc get "<project>" "<slug>"` when you need the exit criteria or intro.

Arguments must carry both `<project>` and `<slug>` — there is no fuzzy resolve. For project-wide discovery: list projects with `claudeplans project list`, list a project's documents with `claudeplans doc list <project>` (both return JSON). The lineage page is the human browser view — open it with `claudeplans project view <project>` which prints its URL. (The search endpoint requires `?q=<term>` and performs keyword search, not enumeration.)

## Work the next phase

- Restate the `current` phase's open tasks to the user.
- Work them **task by task, in conversation** — confirm before each edit, surface commands and output, keep the user in the loop.
- If you delegate implementation work to sub-agents, instruct them never to call the `claudeplans` CLI for writes — the plan doc is mutated only from the main thread.
- As tasks complete, mutate the document via the CLI (re-read `doc phases` to refresh `rev` before each position-sensitive call; if one still races and exits `9`, reuse the `current_rev` it prints and retry):

  Check off a task (TASK_INDEX is 0-based position from `doc phases` output):
  ```shell
  claudeplans task toggle "<project>" "<slug>" "<phase-slug>" <index> --rev <rev>
  ```

  Finishing a phase? Skip the per-task loop. `phase complete` checks every task AND
  sets the phase done in one rev-free call (it checks before the flip, so it never
  trips the done-with-open-tasks warning); or bulk-check without advancing status via
  `task set-checked` — `--all` (rev-free) or an explicit index list (rev-gated once,
  not once per task):
  ```shell
  claudeplans phase complete "<project>" "<slug>" "<phase-slug>"
  claudeplans task set-checked "<project>" "<slug>" "<phase-slug>" --all
  claudeplans task set-checked "<project>" "<slug>" "<phase-slug>" 0 2 4 --rev <rev>
  ```

  Advance the phase:
  ```shell
  claudeplans phase set-status "<project>" "<slug>" "<phase-slug>" doing   # when phase starts
  claudeplans phase set-status "<project>" "<slug>" "<phase-slug>" done    # only at exit criteria
  claudeplans phase set-status "<project>" "<slug>" "<phase-slug>" blocked # if stuck
  ```

  Add a phase mid-plan (then reposition it):
  ```shell
  claudeplans phase add "<project>" "<slug>" "<new-phase-slug>" "<Name>"
  claudeplans phase move "<project>" "<slug>" "<new-phase-slug>" <to_index> --rev <rev>
  ```

  Set a phase's prose — intro / exit criteria / notes (markdown; omitted flags are
  left unchanged, `""` clears; `--<flag>-file <path>` or `-` for stdin avoids shell
  quoting for multi-line prose):
  ```shell
  claudeplans phase set "<project>" "<slug>" "<phase-slug>" --intro "<markdown>" --exit-criteria "<markdown>"
  claudeplans phase set "<project>" "<slug>" "<phase-slug>" --notes-file notes.md
  ```

  Record learnings in a dedicated section as discoveries happen:
  ```shell
  # Create on first use:
  claudeplans section add "<project>" "<slug>" "learnings" "Learnings" --level 2
  # Both commands below REPLACE the whole body — supply the full updated content (prior entries + new entry):
  claudeplans section set "<project>" "<slug>" "learnings" --body "<full updated body>"
  # Equivalent via merge-patch (body is a scalar — patch replaces, does not append):
  claudeplans section patch "<project>" "<slug>" "learnings" --merge-patch '{"body":"<full updated body>"}'
  ```

  Section bodies are **plain markdown** — no HTML spans or pills. A phase's prose lives in its `intro`/`exit_criteria`/`notes` fields (set via `phase set`), not in section bodies; revision/decision cards (`!!!`/`???` admonitions) go in `--notes`.

## Diverge & stop

- If reality diverges from the plan mid-phase, update the relevant phase prose via `phase set` (`--intro`/`--exit-criteria`/`--notes`), or a section body via `section set` / `section patch`, to match.
- **STOP at exit criteria** for explicit user sign-off before setting the phase to `done` and opening the next phase.
- Doc status is **not** automatically set by the service when the last phase completes — once the last phase is `done`, set the doc status explicitly:
  ```shell
  claudeplans doc status "<project>" "<slug>" done
  ```
  A `phases` array where every entry has `status: done` means the plan is complete. A zero-phase array means the plan has no phases — say so and stop; do not propose done.
