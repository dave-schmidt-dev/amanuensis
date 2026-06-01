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

Phase 2a types (Map / Resolve):

- ``Entity`` — canonical entity in the mappings namespace
- ``Resolution`` — (source, atom, surface_form) → entity binding
- ``EntitySupersede`` — supervisor correction at the entity level
- ``ResolutionSupersede`` — supervisor correction at the resolution level

Phase 2b types (Connect):

- ``CrossDocRelation`` — cross-document warrant-bearing edge between
  atoms in DIFFERENT distillations, grounded by shared resolved entities
- ``CrossDocRelationSupersede`` — supervisor correction for a
  cross-doc relation

Phase 2c types (Hierarchize):

- ``Probandum`` — proposition statement at a hierarchy level
  (ultimate / interim / penultimate)
- ``ProbandumEdge`` — supports/attacks/undercuts edge from a parent
  ``Probandum`` to a child ``Probandum`` / ``Atom`` / ``CrossDocRelation``
- ``ProbandumSupersede`` — supervisor correction for a ``Probandum``
- ``ProbandumEdgeSupersede`` — supervisor correction for a
  ``ProbandumEdge``

Public helpers:

- ``compute_id`` — content-addressable id computation for all
  registered content-addressable types (see ``docs/schema-reference.md``).

Filesystem and replay-log writer build on these schemas.
"""

from ._hashing import compute_id
from ._shared import AgentAttribution, OperandRef, RoleAttribution
from .atom import Atom
from .clarification import Clarification
from .cross_doc_relation import CrossDocRelation
from .cross_doc_relation_supersede import CrossDocRelationSupersede
from .entity import Entity
from .entity_supersede import EntitySupersede
from .iteration import IterationDirective
from .probandum import Probandum
from .probandum_edge import ProbandumEdge
from .probandum_edge_supersede import ProbandumEdgeSupersede
from .probandum_supersede import ProbandumSupersede
from .provenance import ProvenanceRecord
from .relation import Relation
from .replay_log import ReplayLogEntry
from .resolution import Resolution
from .resolution_supersede import ResolutionSupersede
from .source_mirror import ParagraphEntry, SourceMirrorManifest
from .vocabulary import OperandTypeSchema, Vocabulary, VocabularyEntry

__all__ = [
    "AgentAttribution",
    "Atom",
    "Clarification",
    "CrossDocRelation",
    "CrossDocRelationSupersede",
    "Entity",
    "EntitySupersede",
    "IterationDirective",
    "OperandRef",
    "OperandTypeSchema",
    "ParagraphEntry",
    "Probandum",
    "ProbandumEdge",
    "ProbandumEdgeSupersede",
    "ProbandumSupersede",
    "ProvenanceRecord",
    "Relation",
    "ReplayLogEntry",
    "Resolution",
    "ResolutionSupersede",
    "RoleAttribution",
    "SourceMirrorManifest",
    "Vocabulary",
    "VocabularyEntry",
    "compute_id",
]
