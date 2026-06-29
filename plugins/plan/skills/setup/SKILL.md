---
name: setup
description: Bring up the claudeplans service locally via the repo's compose stack (make up — Docker Compose, API + view on :8000). Run once after cloning or after a stack update; verify health with the /healthz endpoint.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Read
---

Bring up the claudeplans HTTP service locally. The service exposes the full API and a live HTML view at `:8000`. Once running, the `claudeplans` CLI targets it at `http://127.0.0.1:8000` (the default, or set `CLAUDEPLANS_URL`).

## 1 — Start the service

From the repo root:

```shell
make up
```

This runs `docker compose up --build` in the **foreground**, streaming logs to the terminal — the shell is blocked while the stack is up. Start it in a separate terminal (or background it), then run the health check from another shell. To stop:

```shell
make down
```

## 2 — Verify health

From a separate shell (while `make up` is running):

```shell
curl -fs http://127.0.0.1:8000/healthz
```

A 200 response means the stack is ready. If the curl fails, check the `make up` terminal for errors or run `docker compose logs`. Once the CLI config points at the stack, `claudeplans doctor` is the CLI-native check — it reports reachability plus the server's version/auth mode as JSON (always exit 0).

## 3 — Store the service address

Once the stack is healthy, write the address into the CLI config so subsequent commands need no `--url`:

```shell
claudeplans config set --url http://127.0.0.1:8000 --uid dev
```

The url must match the configured bind (`CLAUDEPLANS_HOST_IP`/`CLAUDEPLANS_HOST_PORT`) — if a non-default bind or friendly-hostname is used, pass that url instead. Verify with:

```shell
claudeplans config show
```

## 4 — Environment

- **Bind address**: controlled by `CLAUDEPLANS_HOST_IP` (default `127.0.0.1`) and `CLAUDEPLANS_HOST_PORT` (default `8000`). An optional `/etc/hosts` friendly-hostname alias (loopback) is supported; the user must add it themselves (requires sudo).
- **Auth**: the dev stack uses a fixed `dev` user with no authentication — set `CLAUDEPLANS_UID=dev` or pass `--uid dev` to the CLI (the default).
- **CLI target**: `CLAUDEPLANS_URL=http://127.0.0.1:8000` is the default; override via `claudeplans config set --url <url>` or the env var if the bind address differs.

## Upgrades

After pulling new repo commits, re-run `make up` — compose rebuilds only changed layers.
