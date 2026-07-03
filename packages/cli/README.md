# claudeplans-cli — the agent client

Typer CLI (console script `claudeplans`) plus a sync library mirror over the
service's HTTP API. Output is compact JSON built for agent consumption;
domain errors map to stable process exit codes shared with the server via
`claudeplans-contracts`.

| Module | Intent |
| --- | --- |
| `cli.py` | Entrypoint — mounts the resource sub-apps and resolves global `--url`/`--uid`. |
| `client.py` | Sync HTTP mirror of the service — a new endpoint gets its client call here first. |
| `config.py` | XDG config file reader/writer (persistent url/uid defaults). |
| `context.py` | The per-invocation application context carried on Typer's `ctx.obj`. |
| `errors.py` | Domain-error → exit-code mapping and the command error boundary. |
| `output.py` | Compact-JSON rendering of read/write replies. |
| `prose.py` | Prose-field resolution: inline flag vs `--<flag>-file` vs stdin. |
| `commands/` | One module per resource group: `doc`, `phase`, `task`, `section`, `project`, `config`, `search`, `schema`, `doctor`. |
