"""Shared vocabulary for documents and phases.

These enums are the controlled vocabulary that both the service and the CLI agree
on. They are StrEnum, so each member's plain string value IS its str() — e.g.
str(DocType.plan) == "plan". No enum-name leakage anywhere: not in f-strings or
logging (str() level), nor on the wire (stored JSON, API payloads). This matches
the StrEnum already used in config.py.
"""

from enum import StrEnum


class DocType(StrEnum):
    plan = "plan"
    research = "research"


class DocStatus(StrEnum):
    draft = "draft"
    active = "active"
    done = "done"
    archived = "archived"


class PhaseStatus(StrEnum):
    todo = "todo"
    doing = "doing"
    done = "done"
    blocked = "blocked"


class SectionPlacement(StrEnum):
    lead = "lead"
    trail = "trail"
