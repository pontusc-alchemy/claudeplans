"""Shared vocabulary for documents and phases.

These enums are the controlled vocabulary that both the service and the CLI agree
on. They subclass str so they serialize as their plain string values into the
stored JSON and the API payloads (no enum-name leakage across the wire).
"""

from enum import Enum


class DocType(str, Enum):
    plan = "plan"
    research = "research"


class DocStatus(str, Enum):
    draft = "draft"
    active = "active"
    done = "done"


class PhaseStatus(str, Enum):
    todo = "todo"
    doing = "doing"
    done = "done"
    blocked = "blocked"
