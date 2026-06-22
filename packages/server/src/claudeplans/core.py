"""Orchestration — the single path a write flows through. Called by API routers.

Per write: validate (claudeplans_contracts model) -> authz (can_write) -> persist
(Repository CAS, with a bounded server-side read-modify-write retry for
commutative deltas so false conflicts never reach the agent) -> emit a change
Event -> invalidate the render cache. Routers stay thin: parse, call core,
return. The functions land in the storage and API phases; this module marks the
seam.
"""
