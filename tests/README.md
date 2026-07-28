# tests — layout intent

- `unit/` — in-process, no live server; roughly one file per module
  (`test_<module>.py`), split by behavior where a module has several.
  `test_config.py` covers `config.py`'s env-driven `Settings` fields.
- `integration/` — live-server and CLI-through-runner flows, split by feature
  (`test_cli_doc.py`, `test_view.py`, …), not by driving mechanism.
- `contract/` — the backend-agnostic Repository contract; every storage
  backend must pass it.
- `eval/` — LLM-authored document payloads exercised against create, to keep
  the API forgiving of real agent output.
- `fixtures/` — canonical document JSON shared across suites.
