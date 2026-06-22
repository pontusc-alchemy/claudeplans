"""The drift linter — NON-RAISING. Structural errors are handled elsewhere.

Structural problems reject at the boundary (pydantic -> HTTP 422). Drift is the
softer class: valid-but-off (stale anchors, legacy markers, status/state
mismatches). This returns warnings and the write still proceeds; the API folds
them into the single {data, warnings[]} envelope. Built out in the data-model
phase; this module marks the seam.
"""
