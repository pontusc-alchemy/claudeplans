"""claudeplans — the FastAPI CRUD service over a structured plan/research store.

The store is canonical; HTML is a derived, live (no-flash) view. Agents write
through the claudeplans-cli client over server-validated endpoints; humans are
read-only.
"""
