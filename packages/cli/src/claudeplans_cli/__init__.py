"""claudeplans-cli — the agent client (thin CLI + library) for the claudeplans service.

Depends ONLY on claudeplans_contracts (shared models, DTOs, error -> exit-code
mapping) so it never drifts from the server; HTTP transport only.
Resource-grouped subcommands and the exit-code contract land in the
agent-client phase.
"""
