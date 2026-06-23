"""API layer: thin routers over core.py, one set of exception handlers, and the
single {data, warnings[]} response wrapper. `install` is the one entry point the
composition root calls to mount everything.
"""

from fastapi import FastAPI

from . import documents, health, phases, search, sections, tasks, view
from .errors import register_exception_handlers


def install(app: FastAPI) -> None:
    """Register the domain-error handlers and mount every router on `app`."""
    register_exception_handlers(app)
    app.include_router(documents.router)
    app.include_router(phases.router)
    app.include_router(tasks.router)
    app.include_router(sections.router)
    app.include_router(view.router)
    app.include_router(search.router)
    app.include_router(health.router)
