# claudeplans

A containerized CRUD service for plan documents and a `claudeplans` CLI client that
talks to it, sharing one set of Pydantic models via `claudeplans-contracts`. The API
and CLI are still skeletons — the runnable shapes (FastAPI app, console script,
quality gate, Docker images) are in place ahead of the feature work.

## Layout

A [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with a
virtual root and three members:

```text
pyproject.toml                 # virtual workspace root: dev group + ruff/ty/pytest config
uv.lock                        # single lock for all members
packages/
├── contracts/                 # claudeplans-contracts — shared Pydantic models
├── server/                    # claudeplans — FastAPI CRUD service (uvicorn entrypoint)
└── cli/                       # claudeplans-cli — CLI client (console script: claudeplans)
tests/{unit,integration,contract,fixtures}/
Dockerfile docker-bake.hcl     # build / serve / ci stages, one image: claudeplans:<stage>
scripts/ci.sh                  # the quality gate (ruff + ty + pytest)
plugins/plan/                  # Claude Code plan plugin (skills only)
```

## Dev inner loop

Requires [uv](https://docs.astral.sh/uv/). The root is virtual, so a plain `uv sync`
installs nothing — use `--all-packages` (wrapped by `make venv`).

```shell
make venv     # uv sync --all-packages — all members editable, for the editor + ty LSP
make check    # full quality gate: ruff check + ruff format --check + ty check + pytest
```

Individual targets: `make lint`, `make fmt`, `make typecheck`, `make test`.

## Docker

One Dockerfile, three stages, built via [Docker Bake](https://docs.docker.com/build/bake/)
into one image (`claudeplans`) tagged by stage:

| Target | Tag | Contents |
| --- | --- | --- |
| `serve` | `claudeplans:serve` | bare runtime — server member installed non-editable into the venv; uvicorn as PID 1 on :8000, non-root |
| `ci` | `claudeplans:ci` | external deps + dev toolchain; runs `scripts/ci.sh` against bind-mounted source |
| `build` | `claudeplans:build` | intermediate — the server's runtime venv |

```shell
make serve-build      # docker buildx bake serve
make serve            # run claudeplans:serve on :8000
make ci               # build claudeplans:ci and run the gate against the working tree
```
