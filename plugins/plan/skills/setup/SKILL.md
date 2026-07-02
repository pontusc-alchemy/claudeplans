---
name: setup
description: Set up claudeplans on this machine — as a client (CLI shim + server address) or as a server (compose stack, optional /etc/hosts alias). Asks which role applies first, then verifies health end-to-end.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Read, AskUserQuestion
---

Set up claudeplans for this machine. There are two roles — ask the user which one applies (AskUserQuestion) **before doing anything else**:

- **Client** — this machine runs the plugin and CLI against a claudeplans server that is already up (locally or on another host).
- **Server** — this machine hosts the claudeplans service via the repo's compose stack.

A machine that hosts the server *and* uses the plugin needs both flows: server first, then client.

## Client setup

### 1 — Verify the CLI shim

The `claudeplans` CLI ships inside this plugin as a `bin/` shim that runs the pinned release via `uvx`, so there is no separate install step — but it requires [uv](https://docs.astral.sh/uv/):

```shell
command -v uv
```

If `uv` is missing, stop and point the user at the [uv install docs](https://docs.astral.sh/uv/getting-started/installation/) — do not install it for them.

Warm and verify the shim (the first run fetches and builds the CLI from the tagged ref; later runs hit the uvx cache):

```shell
claudeplans --version
```

The plugin's `bin/` directory joins the Bash tool's `PATH` while the plugin is enabled. If `claudeplans` does not resolve, check the plugin is enabled (`/plugin`) before debugging anything else. The shim fetches over SSH (`git+ssh://git@github.com/...`), so the machine needs SSH access to the repo.

### 2 — Point the CLI at the server

Ask the user for the server URL if it isn't already established (default local stack: `http://127.0.0.1:8000`; friendly-host binds like `http://claude.plans` also work), then store it:

```shell
claudeplans config set --url <url> --uid dev
```

The dev stack trusts a single fixed `dev` user with no authentication — `--uid dev` is correct until real auth exists.

### 3 — Verify reachability

```shell
claudeplans doctor
```

`doctor` reports reachability plus the server's version/auth mode as JSON (always exit 0). `"reachable": true` → client setup is done. If unreachable, confirm the server is up (server flow below) and that the URL matches the server's bind.

## Server setup

### 1 — Choose the bind (optional friendly hostname)

The default bind is `127.0.0.1:8000` and needs no configuration — skip to step 2 if that's fine.

For a portless friendly URL (e.g. `http://claude.plans`), give the stack its own loopback IP and an `/etc/hosts` alias. **The user must make the sudo edits themselves** — show them the commands, don't run them:

```shell
echo '127.0.0.3 claude.plans' | sudo tee -a /etc/hosts
```

On Linux the whole `127.0.0.0/8` range is loopback with no extra setup. On macOS only `127.0.0.1` exists by default — an additional loopback address needs an explicit alias (`sudo ifconfig lo0 alias 127.0.0.3 up`), and that alias does not persist across reboots without extra setup (flag this to the user; verify current macOS behavior if it matters).

Persist the bind in a repo-root `.env` so plain `make up` reuses it:

```text
CLAUDEPLANS_HOST_IP=127.0.0.3
CLAUDEPLANS_HOST_PORT=80
```

Keep the bind on `127.0.0.0/8` — the no-op auth provider has no authentication, so the port must never leave this host.

### 2 — Start the stack

From the repo root:

```shell
make up
```

This runs `docker compose up --build -d` (detached). The service carries `restart: unless-stopped`, so it survives reboots as long as the Docker daemon itself starts at boot/login — systemd socket/service on Linux, or Docker Desktop's "start at login" on macOS. No extra service unit is needed on either platform. Stop with `make down` (named volumes are kept; to also wipe data run `docker compose down -v` directly).

### 3 — Verify health

```shell
curl -fs http://<bind>/healthz
```

A 200 response means the stack is ready. On failure, check `docker compose logs`.

### 4 — Upgrades & data

After pulling new commits, re-run `make up` — compose rebuilds only changed layers. Document state lives in the named volumes (`claudeplans_data`, `claudeplans_state`) and survives rebuilds, `make down`, and plugin/CLI reinstalls — it is only lost to an explicit `docker compose down -v`.
