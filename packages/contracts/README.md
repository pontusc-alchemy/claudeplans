# claudeplans-contracts — shared wire shapes

The single source of truth for everything that crosses the HTTP boundary:
the document model, wire DTOs, enums, the error → exit-code mapping, and
storage-key derivation. Both the server and the CLI import this package, so
the two cannot drift. Change a wire shape here; never redefine these types
downstream.

| Module | Intent |
| --- | --- |
| `models.py` | The canonical Document/Phase/Task/Section shape — the document model changes here and nowhere else. |
| `dto.py` | Request/response DTOs — the API surface expressed as types. |
| `enums.py` | Shared vocabulary (doc types, doc/phase statuses) used by models, DTOs, and storage metadata. |
| `errors.py` | Domain error types + exit-code mapping — one table drives both the server's HTTP handlers and the CLI's exits. |
| `keys.py` | Storage-key derivation (`uid/project/slug`) — the only place keys are built or parsed. |
| `migrate.py` | Upgrade-on-read schema migration — extend when `models.py` changes shape. |
