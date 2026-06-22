"""Storage layer: the async Repository seam and its backend adapters.

The filesystem adapter (default, local-first) lands in the storage phase; GCS is
deferred behind the same interface.
"""
