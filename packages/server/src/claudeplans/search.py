"""Search — a module (not a package) until full-text justifies a SearchIndex Protocol.

Now: titles via the storage listing + custom metadata, plus an in-memory index of
section/phase HEADINGS built at startup AND kept fresh by subscribing to the
events feed (not only at boot). Built out in the search phase; this module marks
the seam. Full-text search (behind a SearchIndex Protocol) is deferred.
"""
