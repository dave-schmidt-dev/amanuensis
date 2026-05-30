"""``provenance_completeness`` — INV-3 enforcement for atoms.

INV-3: every substrate artifact has a PROV-O record describing the
activity that created it. For an Atom that means:

1. ``atom.provenance_id`` is non-empty (Pydantic already requires the
   field; we additionally require non-empty content).
2. A ProvenanceRecord file exists at
   ``substrate.provenance_path(atom.source_id, atom.provenance_id)``.
3. The on-disk record parses cleanly into ``ProvenanceRecord``
   (delegated to ``Substrate.get_provenance``).
4. The loaded record's ``entity_id`` equals ``atom.id`` — the
   provenance record actually describes THIS atom, not some other one.

Each failure mode produces a distinct ``reason`` so the auditor surface
can group atoms by which step of the lineage check broke.

Design notes
------------
- We depend on ``Substrate`` here (read-only), not the global filesystem,
  so the substrate's path discipline and atomic-write guarantees stand
  between us and the on-disk bytes.
- ``SubstrateInvalidId`` is caught alongside ``SubstrateNotFound``
  because a malformed ``provenance_id`` (slashes, traversal, etc.) is
  semantically "no such record" from the validator's point of view —
  the auditor cannot follow the pointer.
- ``yaml.YAMLError`` and ``pydantic.ValidationError`` are also caught so
  the validator stays total over corrupt-but-present provenance files:
  a future Auditor that walks the substrate must report INV-3 failures,
  not raise into the caller. The reason string carries a one-line
  excerpt of the underlying error for triage.
"""

from __future__ import annotations

import yaml
from pydantic import ValidationError

from amanuensis.fs import Substrate, SubstrateInvalidId, SubstrateNotFound
from amanuensis.schemas import Atom

from ._result import ValidationResult

VALIDATOR_NAME = "provenance_completeness"


def provenance_completeness(atom: Atom, *, substrate: Substrate) -> ValidationResult:
    """Walk an atom's provenance pointer; pass iff every step resolves (INV-3)."""
    if not atom.provenance_id:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            "INV-3 violation: atom.provenance_id is empty",
            subject_id=atom.id,
        )
    try:
        record = substrate.get_provenance(atom.source_id, atom.provenance_id)
    except SubstrateNotFound:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"INV-3 violation: provenance record {atom.provenance_id!r} not found "
            f"for source {atom.source_id!r}",
            subject_id=atom.id,
        )
    except SubstrateInvalidId as exc:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"INV-3 violation: provenance_id is not a valid path component ({exc})",
            subject_id=atom.id,
        )
    except yaml.YAMLError as exc:
        excerpt = str(exc).replace("\n", " ")[:200]
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"INV-3 violation: provenance record for atom {atom.id!r} failed to load: "
            f"YAML parse error: {excerpt}",
            subject_id=atom.id,
        )
    except ValidationError as exc:
        excerpt = str(exc).replace("\n", " ")[:200]
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"INV-3 violation: provenance record for atom {atom.id!r} failed to load: "
            f"schema violation: {excerpt}",
            subject_id=atom.id,
        )
    if record.entity_id != atom.id:
        return ValidationResult.fail(
            VALIDATOR_NAME,
            f"INV-3 violation: provenance record entity_id={record.entity_id!r} "
            f"does not match atom.id={atom.id!r}",
            subject_id=atom.id,
        )
    return ValidationResult.ok(VALIDATOR_NAME, subject_id=atom.id)
