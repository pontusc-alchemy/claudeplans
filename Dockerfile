# base — uv (digest-pinned) + shared env. No `# syntax` directive: the BuildKit
# frontend bundled in Docker 29 supports every feature used here, and a floating
# `docker/dockerfile:1` would contradict the project's pin-everything policy.
FROM python:3.14-slim@sha256:44dd04494ee8f3b538294360e7c4b3acb87c8268e4d0a4828a6500b1eff50061 AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.23@sha256:d0a0a753ab981624b49c97abc98821c1c09f4ca69d1ef5cee69c501be3d88479 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# build — runtime-only venv for the server member. `--package claudeplans` resolves
# just the server + its workspace dep (claudeplans_contracts) + their external deps;
# `--no-editable` installs real files into the venv site-packages (no source copy or
# PYTHONPATH needed in serve); `--no-dev` drops the dev toolchain. The workspace
# members must be present for uv to discover them, so COPY the root manifest, the
# lock, and packages/ first. --locked fails the build if the lock is stale (fail loud).
FROM base AS build
COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/
RUN uv sync --locked --no-dev --no-editable --package claudeplans

# serve — bare runtime: copy the prod venv only. With --no-editable the server lives
# in the venv site-packages, so there is no source to copy and no PYTHONPATH to set.
# exec-form ENTRYPOINT means uvicorn is PID 1 (no shell), so it receives SIGTERM
# directly for graceful shutdown. Single worker: the in-process events feed +
# in-memory index require it (multi-worker is deferred behind a shared broker).
FROM python:3.14-slim@sha256:44dd04494ee8f3b538294360e7c4b3acb87c8268e4d0a4828a6500b1eff50061 AS serve
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
# Non-root runtime user; --chown gives it the venv it needs to read.
RUN useradd --no-create-home --uid 10001 app
COPY --from=build --chown=app:app /opt/venv /opt/venv
WORKDIR /app
USER app
EXPOSE 8000
ENTRYPOINT ["uvicorn", "claudeplans.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ci — every member's external deps + dev toolchain, but NOT the workspace members
# themselves. `--all-packages` pulls in all members' dependency edges; `--no-install-workspace`
# then skips installing the member packages (a plain `--no-install-workspace` would install
# only the dev group, since the virtual root has no deps of its own and excluding the members
# also drops their dependency edges). The member source is bind-mounted at run
# (`docker run -v $PWD:/work`) and imported via PYTHONPATH set in scripts/ci.sh.
# A parallel child of base (not of build): two distinct dependency sets => two syncs is the
# floor. Each sync's RUN layer is cached by Docker and only re-runs when pyproject/uv.lock
# change. packages/ is COPYed so uv can discover the workspace during resolution; it is never
# imported from here.
FROM base AS ci
COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/
RUN uv sync --locked --all-packages --no-install-workspace
ENV PATH=/opt/venv/bin:$PATH \
    VIRTUAL_ENV=/opt/venv
COPY scripts/ci.sh /usr/local/bin/ci.sh
WORKDIR /work
CMD ["bash", "/usr/local/bin/ci.sh"]
