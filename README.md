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
plugins/plan/                  # Claude Code plan plugin (skills + CLI shim in bin/)
```

Each package (and `tests/`) carries a short README mapping module intent —
start there when locating where a change belongs.

## Claude Code plugin

[`plugins/plan/`](plugins/plan/) ships the plan-lifecycle skills **and** the
`claudeplans` CLI — a `bin/` shim that runs the pinned release via
[uvx](https://docs.astral.sh/uv/guides/tools/) (requires `uv` and SSH access to
this repo). Install by adding the repo as a marketplace pinned to a release tag:

```text
/plugin marketplace add pontusc-alchemy/claudeplans@v0.0.1
/plugin install plan@plans
```

Then run the `/plan:setup` skill — it asks whether this machine is a client
(CLI shim + server address) or a server (compose stack + `/etc/hosts` alias)
and walks through the matching flow. The skills cover the whole lifecycle —
`/plan:research` → `write` → `prime` → `iterate` → `review`, plus `update`
and `setup` — mapped in [`plugins/plan/README.md`](plugins/plan/README.md).

**Cutting a release** (manual): the shim pins a full commit SHA (immutable to
uv, so the CLI serves from cache with no per-call network check — a tag ref
would re-fetch on every invocation). Flow: land all `packages/` changes and
note the resulting SHA → update that SHA in `plugins/plan/bin/claudeplans` and
bump `version` in `plugins/plan/.claude-plugin/plugin.json` → commit → tag that
commit → push the tag. Consumers move up by re-adding the marketplace at the
new tag.

## Dev inner loop

Requires [uv](https://docs.astral.sh/uv/). The root is virtual, so a plain `uv sync`
installs nothing — use `--all-packages` (wrapped by `make venv`).

```shell
make venv     # uv sync --all-packages — all members editable, for the editor + ty LSP
make check    # full quality gate: ruff check + ruff format --check + ty check + pytest
```

Individual targets: `make lint`, `make fmt`, `make typecheck`, `make test`.

## Local run (Docker Compose)

[`docker-compose.yml`](docker-compose.yml) builds the `serve` stage and runs it on the filesystem
backend with the dev no-op auth provider — a single fixed `dev` user, no IAP. Two make
targets run it as two separate compose projects that never share state:

```shell
make serve     # stable stack — project `claudeplans`, bind from the checkout's .env; run from the release worktree
make up        # dev stack — default project `claudeplans-dev`, 127.0.0.1:9394, disposable volumes
make down      # stop the dev stack (volumes kept; wipe: docker compose down -v)
make seed      # demo projects (empty/atlas/beacon; idempotent) — brings the dev stack up first
```

It sets the `CLAUDEPLANS_`-prefixed env (`CLAUDEPLANS_AUTH_MODE=noop`,
`CLAUDEPLANS_STORAGE_BACKEND=filesystem`) and points `CLAUDEPLANS_FILESYSTEM__ROOT`
at `/data`, a named volume owned by the non-root `app` user so writes succeed (the
image's `/app` working dir is not writable by uid 10001). A fresh volume inherits
that ownership on first mount; if you swap in a host bind mount or reuse a
root-owned volume, you must make the target writable by uid 10001 yourself. Ports
publish on loopback only (`127.0.0.1`) — the no-op auth provider has no
authentication, so the stack must not be reachable beyond this host.

**Friendly host for the stable stack.** The stable stack's host bind is configurable
via `CLAUDEPLANS_HOST_IP` / `CLAUDEPLANS_HOST_PORT` (a `.env` in the checkout you
serve from, or shell env), defaulting to `127.0.0.1:8000`. On Linux the whole
`127.0.0.0/8` is loopback with no setup, so give the stack its own address and pair
it with an `/etc/hosts` alias:

```shell
echo '127.0.0.3 myplans.local' | sudo tee -a /etc/hosts
printf 'CLAUDEPLANS_HOST_IP=127.0.0.3\nCLAUDEPLANS_HOST_PORT=80\n' > .env
make serve
```

→ `http://myplans.local` — a portless friendly URL with no reverse proxy, and
distinct loopback IPs let several stacks run at once without port collisions. (The
dev stack ignores `.env`: `make up` forces its bind in the recipe so it can never
grab the stable address.)

> **Note:** keep the bind on `127.0.0.0/8`. The no-op auth provider has no
> authentication, so `CLAUDEPLANS_HOST_IP=0.0.0.0` would expose read/write to anyone
> on your network.

**End-to-end.** With the dev stack up and the local venv (`make venv`) on PATH,
create a document with the CLI and read its rendered view in a browser:

```shell
CLAUDEPLANS_URL=http://127.0.0.1:9394 .venv/bin/claudeplans doc create demo --type plan --slug hello --title "Hello Plan"
# → http://127.0.0.1:9394/v1/users/dev/projects/demo/docs/hello/view
```

The CLI defaults to `http://127.0.0.1:8000` and uid `dev`; override with
`--url` / `CLAUDEPLANS_URL` and `--uid` / `CLAUDEPLANS_UID`.

## Serving a release while developing

The stable stack and the dev inner loop share this repo but never a checkout: serve
from a [git worktree](https://git-scm.com/docs/git-worktree) pinned to the release
tag, develop in the main tree.

```shell
git worktree add ../claudeplans.worktrees/serve vX.Y.Z
printf 'CLAUDEPLANS_HOST_IP=127.0.0.3\nCLAUDEPLANS_HOST_PORT=80\n' > ../claudeplans.worktrees/serve/.env
make -C ../claudeplans.worktrees/serve serve
```

- `make serve` (worktree) → compose project `claudeplans`: owns the long-lived
  `claudeplans_data` / `claudeplans_state` volumes and the friendly bind from the
  worktree's `.env` (per-checkout and gitignored — each tree carries its own).
- `make up` / `make down` (dev tree) → default compose project `claudeplans-dev`:
  its own disposable volumes, hard-coded `127.0.0.1:9394` bind. Cycle it freely —
  even `docker compose down -v` only wipes dev state.

**Upgrading the served version:** advance the worktree to the next tag and re-run —
document state lives in the named volumes and survives the rebuild:

```shell
git -C ../claudeplans.worktrees/serve checkout vX.Y.Z   # the new tag
make -C ../claudeplans.worktrees/serve serve
```

## Docker

One Dockerfile, three stages, built via [Docker Bake](https://docs.docker.com/build/bake/)
into one image (`claudeplans`) tagged by stage:

| Target  | Tag                 | Contents                                                                                               |
| ------- | ------------------- | ------------------------------------------------------------------------------------------------------ |
| `serve` | `claudeplans:serve` | bare runtime — server member installed non-editable into the venv; uvicorn as PID 1 on :8000, non-root |
| `ci`    | `claudeplans:ci`    | external deps + dev toolchain; runs `scripts/ci.sh` against bind-mounted source                        |
| `build` | `claudeplans:build` | intermediate — the server's runtime venv                                                               |

```shell
make serve-build      # docker buildx bake serve
make serve            # bring up the stable stack (compose project `claudeplans`)
make ci               # build claudeplans:ci and run the gate against the working tree
```
