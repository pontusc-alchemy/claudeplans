"""Shared contracts: models, enums, DTOs, and the error -> exit-code mapping.

Leaf package imported by BOTH the claudeplans service and the claudeplans-cli client, so
the two never drift on schema or error semantics. Models land in the data-model
phase; this skeleton defines only the stable error/exit-code contract that the
storage seam, core orchestration, API handlers, and CLI all reference.
"""
