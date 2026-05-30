"""Public Pydantic schemas for amanuensis distillation substrate.

Phase 1 types:

- ``Atom`` — leaf unit (reduced Toulmin assertion)
- ``Relation`` — intra-document warrant-bearing edge between atoms
- ``AgentAttribution`` — actor identity (human / LLM + role)
- ``RoleAttribution`` — audit event on a substrate artifact
- ``OperandRef`` — typed reference to an operand in an Atom's predicate
- ``ProvenanceRecord`` — W3C PROV-O subset for substrate artifact lineage
- ``Clarification`` — open / resolved question on substrate artifacts
- ``IterationDirective`` — human instruction to revise phase outputs
- ``ReplayLogEntry`` — append-only record of a single substrate activity
- ``Vocabulary`` / ``VocabularyEntry`` / ``OperandTypeSchema`` — closed
  predicate registry

Public helpers:

- ``compute_id`` — content-addressable id computation for the five
  content-addressable types (see ``docs/schema-reference.md``).

Filesystem (M1.6) and replay-log writer (M1.7) build on these schemas.
"""

from ._hashing import compute_id
from ._shared import AgentAttribution, OperandRef, RoleAttribution
from .atom import Atom
from .clarification import Clarification
from .iteration import IterationDirective
from .provenance import ProvenanceRecord
from .relation import Relation
from .replay_log import ReplayLogEntry
from .source_mirror import ParagraphEntry, SourceMirrorManifest
from .vocabulary import OperandTypeSchema, Vocabulary, VocabularyEntry

__all__ = [
    "AgentAttribution",
    "Atom",
    "Clarification",
    "IterationDirective",
    "OperandRef",
    "OperandTypeSchema",
    "ParagraphEntry",
    "ProvenanceRecord",
    "Relation",
    "ReplayLogEntry",
    "RoleAttribution",
    "SourceMirrorManifest",
    "Vocabulary",
    "VocabularyEntry",
    "compute_id",
]
