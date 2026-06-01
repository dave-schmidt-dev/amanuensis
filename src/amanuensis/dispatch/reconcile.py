"""Reconciliation gate — consume dispatch outputs, validate, commit (M7.4).

The dispatch driver (M6.5) lands each role's structured payload at
``dispatch/outputs/<role>-<inputs_hash>/output.yaml``. The reconciliation
gate is the bridge between that staging area and the substrate proper:

1. Walk every ``output.yaml`` under ``dispatch/outputs/`` (skipping
   anything under the ``_consumed/`` subtree).
2. Parse defensively — the role outputs are model-produced YAML and can
   legitimately deviate from the operational schema in the brief. Parse
   failures route the offending file into ``ReconcileResult.errors``;
   they are left in place for manual inspection so the operator can
   triage without losing context.
3. For each parsed payload:

   - **Extractor outputs** produce candidate ``Atom`` + ``Relation``
     records. Each candidate is run through the seven M2 validators.
     Atoms that pass go to the substrate; atoms that fail raise a
     clarification on the validator's failure reason. Relations that
     carry ``warrant_defensibility == "contested"`` auto-raise a
     ``warrant-defensibility-contested`` clarification (CR-7).
   - **Auditor outputs** carry verbatim clarifications (raised) and
     ``rejected_atoms`` entries; contested rejections also raise a
     ``warrant-defensibility-contested`` clarification.

4. After every artifact for an output file is processed, the file is
   moved into ``dispatch/outputs/_consumed/<role>-<hash>/output.yaml``
   (atomic same-FS rename) so a second reconcile run is a no-op.

The whole drain runs under :func:`acquire_workspace_lock` so a parallel
``distill`` / ``dispatch`` / web POST does not race with us on substrate
writes.

Public surface
--------------
- :class:`ReconcileResult` — structured summary returned to callers.
- :func:`reconcile_outputs` — the entry point invoked by the CLI.

The CLI command (``amanuensis reconcile``) is registered in
:mod:`amanuensis.cli` and lives in :mod:`amanuensis.cli.reconcile`.

CR-7 (warrant-defensibility-contested clarification)
----------------------------------------------------
The Auditor surface is required to escalate any relation whose warrant
it cannot defensibly underwrite. The reconciliation gate is the choke
point that converts that signal — present in either an extractor's
relation payload OR an auditor's rejected_atoms entry — into an open
``Clarification`` recorded on the substrate. The clarification's
``kind`` field does not exist in the schema; we encode the kind in the
``raised_by_activity`` slot (``"reconcile-warrant-contested"``) and a
caller-visible discriminator on the question text. The
``context_refs`` list carries the relation id (or atom id) under
review so a human resolving the clarification can navigate back.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import ValidationError

from amanuensis.fs import (
    CrossSourceConstraintViolation,
    ReplayLog,
    SharedEntityGateViolation,
    Substrate,
    SubstrateNotFound,
    SubstrateSnapshotCorrupt,
    acquire_workspace_lock,
)
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    CrossDocRelation,
    Entity,
    OperandRef,
    ProvenanceRecord,
    Relation,
    Resolution,
    RoleAttribution,
    Vocabulary,
    compute_id,
)
from amanuensis.validators import (
    ValidationResult,
    citation_ledger,
    closed_vocabulary,
    lineage_closure,
    provenance_completeness,
    scale_anchor,
    schema_check,
    universe_check,
)

__all__ = ["ReconcileResult", "reconcile_outputs"]


# Sentinel directory the gate moves consumed outputs under.
_CONSUMED_DIRNAME: str = "_consumed"

# Regex that matches map-* role output directory names.
# Group 1 = role (map-resolve | map-audit), Group 2 = inputs hash.
# Hash chars stay deliberately permissive (\w): production hashes are
# [a-f0-9] from SHA-256 but synthetic test fixtures use arbitrary
# repeated chars for visual identification.
_MAP_ROLE_RE = re.compile(r"^(map-(?:resolve|audit))-(\w+)$")

# ``raised_by_activity`` values that this module emits on Clarifications.
# Since T1.8 the Clarification schema also has a ``kind`` discriminator
# (see ``_kind_for_activity`` below for the mapping). These activity
# strings still drive filtering / question-text prefixing per CR-7.
_KIND_WARRANT_CONTESTED: str = "warrant-defensibility-contested"
_KIND_VALIDATION_FAILED: str = "atom-validation-failed"

# Phase 2b M4 — Connector-role reconciliation. Activity tag the
# auto-raised ``resolution-ambiguous`` Clarification carries so a human
# resolving the open item can recognize who raised it.
_KIND_CONNECT_RESOLUTION_AMBIGUOUS: str = "connect-resolution-ambiguous"


class CandidateShapeError(ValueError):
    """Raised when a Connector candidate fails pydantic / schema validation.

    The reconciler propagates this to the caller (dispatch driver) rather
    than auto-raising a clarification — a malformed candidate is a model
    failure, not a substrate-state ambiguity. The driver records it in
    ``ReconcileResult.errors``.
    """


# --- Result dataclass --------------------------------------------------


@dataclass(slots=True)
class ReconcileResult:
    """Structured summary of one ``reconcile_outputs`` invocation.

    Attributes:
        atoms_committed: Ids of atoms written to the substrate.
        relations_committed: Ids of relations written to the substrate.
        clarifications_raised: Ids of open clarifications written.
        outputs_consumed: Output files that were processed AND moved to
            ``dispatch/outputs/_consumed/<role>-<hash>/output.yaml``.
        errors: ``(path, reason)`` pairs for output files that failed to
            parse or process. The offending file is left in place at the
            original location so the operator can triage manually.
    """

    atoms_committed: list[str] = field(default_factory=list)
    relations_committed: list[str] = field(default_factory=list)
    clarifications_raised: list[str] = field(default_factory=list)
    outputs_consumed: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


# --- Public entry point ------------------------------------------------


def reconcile_outputs(
    *,
    substrate: Substrate,
    workspace_root: Path,
) -> ReconcileResult:
    """Reconcile every pending dispatch output into the substrate.

    Walks ``<workspace_root>/dispatch/outputs/`` for every
    ``<role>-<hash>/output.yaml`` (skipping the ``_consumed/`` subtree),
    routes by role to the extractor or auditor reconciliation path, and
    moves each consumed file into ``_consumed/`` so the operation is
    idempotent. The whole walk runs under the workspace flock.

    Args:
        substrate: A ``Substrate`` already bound to ``workspace_root``.
            Callers construct it before reconcile so any INV-1 failure
            surfaces with their preferred error handling.
        workspace_root: Workspace root directory (must contain the
            ``amanuensis.yaml`` marker — the flock helper re-checks).

    Returns:
        A populated :class:`ReconcileResult`. Even on partial failure the
        returned result captures every successful write; ``errors`` names
        the output files that could not be processed.
    """
    result = ReconcileResult()
    outputs_root = workspace_root / "dispatch" / "outputs"
    if not outputs_root.is_dir():
        return result

    with acquire_workspace_lock(workspace_root):
        # ``known_source_ids`` is computed once per reconcile run from the
        # on-disk distillation tree; universe_check needs it as a set.
        # Re-computing per file would be wasted work — distillations
        # cannot appear during the run because we hold the flock.
        known_source_ids = _list_known_source_ids(workspace_root)

        # Pre-load vocabulary snapshots lazily on first need; a single
        # reconcile run may touch many sources and we want one warning,
        # not N, when a snapshot is missing.
        vocab_cache: dict[str, Vocabulary | None] = {}

        for output_path in _iter_pending_outputs(outputs_root):
            role, inputs_hash = _parse_output_dir_name(output_path.parent.name)
            try:
                _process_one_output(
                    output_path=output_path,
                    role=role,
                    inputs_hash=inputs_hash,
                    substrate=substrate,
                    workspace_root=workspace_root,
                    known_source_ids=known_source_ids,
                    vocab_cache=vocab_cache,
                    result=result,
                )
            except Exception as exc:  # pylint: disable=broad-except
                # Defensive: any uncaught failure for one file should not
                # poison the rest of the drain. Record + continue.
                result.errors.append((output_path, f"reconcile failed: {exc}"))
                continue

            # Move the consumed file under _consumed/<role>-<hash>/output.yaml.
            # If the move itself fails we surface that as an error rather
            # than silently letting a second reconcile re-process it.
            try:
                consumed_path = _move_to_consumed(output_path, outputs_root)
            except Exception as exc:  # pylint: disable=broad-except
                result.errors.append(
                    (output_path, f"consumed-move failed: {exc}"),
                )
                continue
            result.outputs_consumed.append(consumed_path)

    return result


# --- Output discovery / path helpers -----------------------------------


def _iter_pending_outputs(outputs_root: Path) -> list[Path]:
    """Yield every ``output.yaml`` under ``outputs_root`` except ``_consumed/``.

    Returns a materialised, sorted list so the drain order is
    deterministic (filesystem iter order varies across platforms /
    filesystems). Output dirs whose name does not match the canonical
    ``<role>-<hash>`` shape are skipped — they are not ours to process.
    """
    out: list[Path] = []
    for child in sorted(outputs_root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name == _CONSUMED_DIRNAME:
            continue
        # The dir name is "<role>-<inputs_hash>". Require at least one
        # hyphen and a non-empty role / hash so we do not pick up stray
        # sibling directories an operator may have planted.
        try:
            _parse_output_dir_name(child.name)
        except ValueError:
            continue
        candidate = child / "output.yaml"
        if not candidate.is_file():
            continue
        out.append(candidate)
    return out


def _parse_output_dir_name(name: str) -> tuple[str, str]:
    """Split ``<role>-<hash>`` into ``(role, hash)``.

    Map roles (``map-resolve``, ``map-audit``) contain a hyphen in the role
    name itself, so a naïve first-hyphen split would produce ``("map",
    "resolve-<hash>")``. The regex branch handles them explicitly.
    Single-component roles (extractor / auditor / ...) fall through to
    the ``partition`` path.

    Raises :class:`ValueError` for any shape that cannot be parsed, so
    the iterator can skip non-output dirs.
    """
    m = _MAP_ROLE_RE.match(name)
    if m:
        return m.group(1), m.group(2)
    if "-" not in name:
        raise ValueError(f"output dir name {name!r} has no hyphen")
    role, _, inputs_hash = name.partition("-")
    if not role or not inputs_hash:
        raise ValueError(f"output dir name {name!r} has empty role or hash component")
    return role, inputs_hash


def _move_to_consumed(output_path: Path, outputs_root: Path) -> Path:
    """Atomic-rename ``output.yaml`` under ``_consumed/<role>-<hash>/``."""
    # output_path = .../dispatch/outputs/<role>-<hash>/output.yaml
    role_hash_dir = output_path.parent.name
    dest_dir = outputs_root / _CONSUMED_DIRNAME / role_hash_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / output_path.name
    output_path.rename(dest_path)
    return dest_path


def _list_known_source_ids(workspace_root: Path) -> set[str]:
    """Walk ``distillations/`` once; return the set of source ids on disk."""
    dist_root = workspace_root / "distillations"
    if not dist_root.is_dir():
        return set()
    return {p.name for p in dist_root.iterdir() if p.is_dir()}


# --- Output parsing / dispatch -----------------------------------------


def _process_one_output(
    *,
    output_path: Path,
    role: str,
    inputs_hash: str,
    substrate: Substrate,
    workspace_root: Path,
    known_source_ids: set[str],
    vocab_cache: dict[str, Vocabulary | None],
    result: ReconcileResult,
) -> None:
    """Parse one ``output.yaml`` and route by role.

    Adds successes to ``result``; parse errors are appended to
    ``result.errors`` and the function returns cleanly (the caller
    leaves the file in place rather than moving it to ``_consumed/``).
    """
    text = output_path.read_text(encoding="utf-8")
    try:
        raw: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        result.errors.append((output_path, f"yaml parse error: {exc}"))
        raise
    if not isinstance(raw, dict):
        result.errors.append(
            (output_path, f"expected top-level mapping, got {type(raw).__name__}"),
        )
        raise ValueError("output payload is not a mapping")
    payload: dict[str, Any] = cast("dict[str, Any]", raw)

    if role.startswith("extractor"):
        _process_extractor_output(
            payload=payload,
            inputs_hash=inputs_hash,
            substrate=substrate,
            known_source_ids=known_source_ids,
            vocab_cache=vocab_cache,
            result=result,
        )
    elif role.startswith("auditor"):
        _process_auditor_output(
            payload=payload,
            substrate=substrate,
            result=result,
        )
    elif role == "map-resolve":
        _process_map_resolve_output(
            payload=payload,
            inputs_hash=inputs_hash,
            substrate=substrate,
            workspace_root=workspace_root,
            result=result,
        )
    elif role == "map-audit":
        _process_map_audit_output(
            payload=payload,
            substrate=substrate,
            workspace_root=workspace_root,
            result=result,
        )
    elif role == "connect":
        _process_connect_output(
            payload=payload,
            inputs_hash=inputs_hash,
            substrate=substrate,
            workspace_root=workspace_root,
            result=result,
        )
    else:
        # Unknown role: not an error — the operator may dispatch roles
        # whose reconciliation is implemented elsewhere. Record nothing
        # and let the caller move the file to _consumed/ (idempotency
        # depends on it).
        return


# --- Extractor path ----------------------------------------------------


def _process_extractor_output(
    *,
    payload: dict[str, Any],
    inputs_hash: str,
    substrate: Substrate,
    known_source_ids: set[str],
    vocab_cache: dict[str, Vocabulary | None],
    result: ReconcileResult,
) -> None:
    """Reconcile one extractor output payload."""
    proposed_atoms = _as_list(payload.get("proposed_atoms"))
    proposed_relations = _as_list(payload.get("proposed_relations"))

    # First pass: build + validate + commit atoms. Track a mapping from
    # whatever id the extractor used (content_hash | local label) to the
    # canonical atom id we computed so the relation pass can resolve
    # subject/object references back to substrate ids.
    local_to_committed: dict[str, str] = {}

    for raw_atom in proposed_atoms:
        if not isinstance(raw_atom, dict):
            continue
        atom_dict: dict[str, Any] = cast("dict[str, Any]", raw_atom)
        _commit_one_atom(
            raw=atom_dict,
            inputs_hash=inputs_hash,
            substrate=substrate,
            known_source_ids=known_source_ids,
            vocab_cache=vocab_cache,
            local_to_committed=local_to_committed,
            result=result,
        )

    # Second pass: relations. CR-7 — contested warrant auto-raises a
    # clarification regardless of whether the relation itself commits.
    for raw_rel in proposed_relations:
        if not isinstance(raw_rel, dict):
            continue
        rel_dict: dict[str, Any] = cast("dict[str, Any]", raw_rel)
        _commit_one_relation(
            raw=rel_dict,
            inputs_hash=inputs_hash,
            substrate=substrate,
            local_to_committed=local_to_committed,
            result=result,
        )


def _commit_one_atom(
    *,
    raw: dict[str, Any],
    inputs_hash: str,
    substrate: Substrate,
    known_source_ids: set[str],
    vocab_cache: dict[str, Vocabulary | None],
    local_to_committed: dict[str, str],
    result: ReconcileResult,
) -> None:
    """Build, validate, and (if clean) commit one extractor-proposed atom."""
    # The extractor's "local id" is whatever field they used to reference
    # the atom from a relation: a ``content_hash`` or an explicit ``id``
    # or — when neither is present — None.
    local_id = _coerce_optional_str(raw.get("id")) or _coerce_optional_str(raw.get("content_hash"))

    source_id = _coerce_optional_str(raw.get("source_id"))
    if not source_id:
        result.errors.append(
            (Path("(in-memory-atom)"), f"proposed_atom missing source_id: {raw!r}"[:200]),
        )
        return

    # Construct the Atom with a placeholder provenance_id; provenance_id
    # is volatile for canonical-form hashing so the computed atom id is
    # stable regardless of the placeholder.
    try:
        atom_draft = _build_atom_draft(raw=raw, source_id=source_id)
    except ValueError as exc:
        # Schema-level failure: we cannot construct the atom at all.
        # Surface as an error rather than a clarification — the model's
        # output is malformed in a way that has no semantic recovery
        # path other than re-running the role.
        result.errors.append(
            (Path("(in-memory-atom)"), f"atom-build failed: {exc}"),
        )
        return

    atom_id = compute_id(atom_draft)

    # PROV record: entity_id == atom_id, attribution to the extractor.
    # Phase 1 simplicity: use a constant attribution per the brief.
    started_at = datetime.now(UTC)
    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="atom",
        entity_id=atom_id,
        activity="extractor-reconcile",
        activity_started_at=started_at,
        activity_ended_at=started_at,
        used_entity_ids=[source_id],
        was_attributed_to=AgentAttribution(
            kind="llm",
            identifier="extractor",
            role="extractor",
        ),
        was_influenced_by=[inputs_hash] if inputs_hash else [],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = prov_draft.model_copy(update={"id": prov_id})

    # Finalize the atom with the real prov pointer. provenance_id is
    # volatile for hashing so atom.id is unchanged.
    atom = atom_draft.model_copy(update={"id": atom_id, "provenance_id": prov_id})

    # Write the PROV record FIRST so provenance_completeness sees it. We
    # do NOT write the atom yet — if validation fails we must not leave
    # a half-committed pair. The PROV record is content-addressable; if
    # the atom is rejected the PROV file remains as a harmless orphan
    # (the auditor can clean it up via a future GC). This matches the
    # discipline elsewhere (iteration.py, clarification.py).
    substrate.add_provenance(source_id, prov)

    # Run all seven M2 validators that apply to atoms.
    failures = _run_atom_validators(
        atom=atom,
        substrate=substrate,
        known_source_ids=known_source_ids | {source_id},
        vocab_cache=vocab_cache,
    )

    if failures:
        # Raise a clarification on the FIRST failure (auditor surface
        # convention: first-failure-wins). Do not commit the atom.
        first = failures[0]
        clar_id = _raise_clarification(
            substrate=substrate,
            source_id=source_id,
            question=(
                f"Atom {atom_id} failed validator {first.validator!r}: "
                f"{first.reason}. Reaffirm, narrow, or reject?"
            ),
            context_refs=[atom_id],
            options=["reaffirm", "narrow", "reject"],
            activity=_KIND_VALIDATION_FAILED,
            identifier="reconcile",
            role="auditor",
        )
        result.clarifications_raised.append(clar_id)
        return

    # All validators passed; commit the atom.
    substrate.add_atom(source_id, atom)
    result.atoms_committed.append(atom_id)
    if local_id:
        local_to_committed[local_id] = atom_id
    # Also self-map by canonical id so a relation that references an
    # atom by its computed id resolves identically.
    local_to_committed[atom_id] = atom_id


def _build_atom_draft(*, raw: dict[str, Any], source_id: str) -> Atom:
    """Construct an ``Atom`` from one extractor ``proposed_atoms`` entry.

    Uses placeholder id + provenance_id; the caller computes the real id
    and writes back the real provenance pointer. Raises ``ValueError`` if
    the dict shape cannot be coerced into an Atom.
    """
    section_path_raw = raw.get("section_path", [])
    if not isinstance(section_path_raw, list):
        raise ValueError(f"section_path must be a list, got {type(section_path_raw).__name__}")
    section_path = [str(seg) for seg in cast("list[Any]", section_path_raw)]

    char_span_raw = raw.get("char_span")
    if (
        not isinstance(char_span_raw, (list, tuple))
        or len(cast("list[Any] | tuple[Any, ...]", char_span_raw)) != 2
    ):
        raise ValueError(f"char_span must be a 2-list/tuple, got {char_span_raw!r}")
    char_span_seq = cast("list[Any] | tuple[Any, ...]", char_span_raw)
    char_span: tuple[int, int] = (int(char_span_seq[0]), int(char_span_seq[1]))

    scale_anchor_raw = raw.get("scale_anchor", "")
    if scale_anchor_raw not in {"sentence", "paragraph", "section", "document"}:
        raise ValueError(f"scale_anchor {scale_anchor_raw!r} not in INV-6 closed set")
    scale_anchor_lit = cast(
        "Literal['sentence', 'paragraph', 'section', 'document']", scale_anchor_raw
    )

    kind_raw = raw.get("kind", "claim")
    if kind_raw not in {"claim", "data", "qualifier", "rebuttal"}:
        raise ValueError(f"kind {kind_raw!r} not in atom-kind closed set")
    kind_lit = cast("Literal['claim', 'data', 'qualifier', 'rebuttal']", kind_raw)

    operands_raw = raw.get("operands", [])
    if not isinstance(operands_raw, list):
        raise ValueError(f"operands must be a list, got {type(operands_raw).__name__}")
    operands: list[OperandRef] = []
    for op_raw in cast("list[Any]", operands_raw):
        if not isinstance(op_raw, dict):
            raise ValueError(f"operand must be a dict, got {type(op_raw).__name__}")
        op_dict: dict[str, Any] = cast("dict[str, Any]", op_raw)
        operands.append(
            OperandRef(
                role=str(op_dict.get("role", "")),
                kind=cast(
                    "Literal['entity', 'literal', 'doc_span']",
                    op_dict.get("kind", "entity"),
                ),
                value=str(op_dict.get("value", "")),
                type_hint=_coerce_optional_str(op_dict.get("type_hint")),
            )
        )

    qualifier_level_raw = raw.get("qualifier_level")
    qualifier_level: Literal["high", "medium", "low", "contested"] | None
    if qualifier_level_raw is None:
        qualifier_level = None
    elif qualifier_level_raw in {"high", "medium", "low", "contested"}:
        qualifier_level = cast("Literal['high', 'medium', 'low', 'contested']", qualifier_level_raw)
    else:
        raise ValueError(f"qualifier_level {qualifier_level_raw!r} not in closed set")

    # Build a placeholder RoleAttribution so the audit trail is non-empty.
    role_attribution = RoleAttribution(
        agent=AgentAttribution(
            kind="llm",
            identifier="extractor",
            role="extractor",
        ),
        activity="proposed",
        at=datetime.now(UTC),
    )

    return Atom(
        id="a-" + "0" * 16,
        source_id=source_id,
        section_path=section_path,
        paragraph_index=int(raw.get("paragraph_index", 0)),
        sentence_index=None,
        char_span=char_span,
        scale_anchor=scale_anchor_lit,
        kind=kind_lit,
        predicate=str(raw.get("predicate", "")),
        operands=operands,
        narrative=str(raw.get("narrative", "")),
        qualifier_level=qualifier_level,
        qualifier_basis=_coerce_optional_str(raw.get("qualifier_basis")),
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )


def _run_atom_validators(
    *,
    atom: Atom,
    substrate: Substrate,
    known_source_ids: set[str],
    vocab_cache: dict[str, Vocabulary | None],
) -> list[ValidationResult]:
    """Run the six atom validators; return the failure list (empty == clean)."""
    failures: list[ValidationResult] = []

    for runner in (
        lambda: schema_check(atom, model_class=Atom),
        lambda: citation_ledger(atom),
        lambda: universe_check(atom, known_source_ids=known_source_ids),
        lambda: scale_anchor(atom),
        lambda: provenance_completeness(atom, substrate=substrate),
    ):
        result = runner()
        if not result.passed:
            failures.append(result)

    # closed_vocabulary needs the per-distillation snapshot; skip with a
    # synthetic failure if the snapshot is missing so the operator sees
    # the gap instead of silent admission.
    vocab = _get_vocab(substrate, atom.source_id, vocab_cache)
    if vocab is None:
        failures.append(
            ValidationResult.fail(
                "closed_vocabulary",
                f"vocabulary snapshot unavailable for source {atom.source_id!r}",
                subject_id=atom.id,
            )
        )
    else:
        cv_result = closed_vocabulary(atom, vocabulary=vocab)
        if not cv_result.passed:
            failures.append(cv_result)

    return failures


def _get_vocab(
    substrate: Substrate,
    source_id: str,
    cache: dict[str, Vocabulary | None],
) -> Vocabulary | None:
    """Memoised snapshot lookup; ``None`` if missing or corrupt."""
    if source_id in cache:
        return cache[source_id]
    try:
        vocab = substrate.get_vocabulary_snapshot(source_id)
    except (SubstrateNotFound, SubstrateSnapshotCorrupt):
        cache[source_id] = None
        return None
    cache[source_id] = vocab
    return vocab


# --- Relation path -----------------------------------------------------


def _commit_one_relation(
    *,
    raw: dict[str, Any],
    inputs_hash: str,
    substrate: Substrate,
    local_to_committed: dict[str, str],
    result: ReconcileResult,
) -> None:
    """Build, validate, and (if clean) commit one extractor-proposed relation.

    CR-7: regardless of whether the relation commits, a
    ``warrant_defensibility == "contested"`` payload auto-raises a
    ``warrant-defensibility-contested`` clarification.
    """
    source_id = _coerce_optional_str(raw.get("source_id"))
    if not source_id:
        result.errors.append(
            (Path("(in-memory-relation)"), f"proposed_relation missing source_id: {raw!r}"[:200]),
        )
        return

    # Resolve the subject/object atom references. The brief allows two
    # conventions: ``subject_atom_id`` / ``object_atom_id`` (brief shape)
    # or ``from_atom_id`` / ``to_atom_id`` (schema shape). Try both.
    from_local = _coerce_optional_str(raw.get("from_atom_id") or raw.get("subject_atom_id"))
    to_local = _coerce_optional_str(raw.get("to_atom_id") or raw.get("object_atom_id"))

    # Map through local_to_committed; an unresolved local id falls
    # through as-is so lineage_closure surfaces the real failure path.
    from_atom_id = local_to_committed.get(from_local, from_local) if from_local else ""
    to_atom_id = local_to_committed.get(to_local, to_local) if to_local else ""

    warrant_defensibility = raw.get("warrant_defensibility", "conventional")

    # CR-7: contested warrants on a relation ALWAYS raise the
    # clarification, even if the relation itself goes on to commit or
    # fail validation. We do this BEFORE attempting to build the
    # relation so a malformed-but-contested payload still surfaces.
    contested_clar_id: str | None = None
    if warrant_defensibility == "contested":
        warrant_text = str(raw.get("warrant", "(no warrant text)"))
        # Reference the local id in the question so a human reading
        # the clarification can navigate even before the relation is
        # actually committed (or finds out it never will be).
        ref = from_local or to_local or "(unresolved)"
        contested_clar_id = _raise_clarification(
            substrate=substrate,
            source_id=source_id,
            question=(
                f"Auditor flagged the warrant for relation {ref!r} as contested: "
                f"{warrant_text!r}. Reaffirm, narrow, or reject?"
            ),
            context_refs=[v for v in (from_atom_id, to_atom_id) if v],
            options=["reaffirm", "narrow", "reject"],
            activity=_KIND_WARRANT_CONTESTED,
            identifier="reconcile",
            role="auditor",
        )
        result.clarifications_raised.append(contested_clar_id)

    # Build the relation. If construction fails we record an error and
    # exit — the contested-clarification has already been raised above
    # if applicable.
    try:
        relation_draft = _build_relation_draft(
            raw=raw,
            source_id=source_id,
            from_atom_id=from_atom_id,
            to_atom_id=to_atom_id,
        )
    except ValueError as exc:
        result.errors.append(
            (Path("(in-memory-relation)"), f"relation-build failed: {exc}"),
        )
        return

    relation_id = compute_id(relation_draft)
    started_at = datetime.now(UTC)
    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="relation",
        entity_id=relation_id,
        activity="extractor-reconcile-relation",
        activity_started_at=started_at,
        activity_ended_at=started_at,
        used_entity_ids=[v for v in (from_atom_id, to_atom_id) if v],
        was_attributed_to=AgentAttribution(
            kind="llm",
            identifier="extractor",
            role="extractor",
        ),
        was_influenced_by=[inputs_hash] if inputs_hash else [],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = prov_draft.model_copy(update={"id": prov_id})

    relation = relation_draft.model_copy(update={"id": relation_id, "provenance_id": prov_id})

    # Write the PROV first (same discipline as atoms). If lineage_closure
    # fails we leave the PROV as a harmless orphan rather than racing a
    # rollback.
    substrate.add_provenance(source_id, prov)

    # schema_check passes by construction (we just built it). The
    # discriminating relation validator is lineage_closure.
    lc_result = lineage_closure(relation, substrate=substrate)
    if not lc_result.passed:
        # Raise a clarification but do not commit the relation. If we
        # already raised a contested clarification above, do not raise a
        # second one — operators should not see two open clarifications
        # for the same relation payload.
        if contested_clar_id is None:
            clar_id = _raise_clarification(
                substrate=substrate,
                source_id=source_id,
                question=(
                    f"Relation {relation_id} failed lineage_closure: "
                    f"{lc_result.reason}. Reaffirm, narrow, or reject?"
                ),
                context_refs=[relation_id],
                options=["reaffirm", "narrow", "reject"],
                activity=_KIND_VALIDATION_FAILED,
                identifier="reconcile",
                role="auditor",
            )
            result.clarifications_raised.append(clar_id)
        return

    substrate.add_relation(source_id, relation)
    result.relations_committed.append(relation_id)


def _build_relation_draft(
    *,
    raw: dict[str, Any],
    source_id: str,
    from_atom_id: str,
    to_atom_id: str,
) -> Relation:
    """Construct a ``Relation`` from one extractor ``proposed_relations`` entry."""
    kind_raw = raw.get("kind") or raw.get("relation_type") or "supports"
    if kind_raw not in {"supports", "attacks", "undercuts"}:
        raise ValueError(f"relation kind {kind_raw!r} not in closed set")
    kind_lit = cast("Literal['supports', 'attacks', 'undercuts']", kind_raw)

    defensibility_raw = raw.get("warrant_defensibility", "conventional")
    if defensibility_raw not in {
        "literature-backed",
        "methodology-derived",
        "conventional",
        "contested",
    }:
        raise ValueError(f"warrant_defensibility {defensibility_raw!r} not in closed set")
    defensibility_lit = cast(
        "Literal['literature-backed', 'methodology-derived', 'conventional', 'contested']",
        defensibility_raw,
    )

    confidence_raw = raw.get("confidence", "medium")
    if confidence_raw not in {"high", "medium", "low"}:
        raise ValueError(f"confidence {confidence_raw!r} not in closed set")
    confidence_lit = cast("Literal['high', 'medium', 'low']", confidence_raw)

    role_attribution = RoleAttribution(
        agent=AgentAttribution(
            kind="llm",
            identifier="extractor",
            role="extractor",
        ),
        activity="proposed",
        at=datetime.now(UTC),
    )

    return Relation(
        id="r-" + "0" * 16,
        source_id=source_id,
        from_atom_id=from_atom_id,
        to_atom_id=to_atom_id,
        kind=kind_lit,
        warrant=str(raw.get("warrant", "")),
        warrant_defensibility=defensibility_lit,
        warrant_basis=str(raw.get("warrant_basis", "")),
        confidence=confidence_lit,
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )


# --- Auditor path ------------------------------------------------------


def _process_auditor_output(
    *,
    payload: dict[str, Any],
    substrate: Substrate,
    result: ReconcileResult,
) -> None:
    """Reconcile one auditor output payload.

    Three top-level keys are honoured:

    - ``accepted_atom_ids``: informational only (the atoms are already
      committed via the extractor pass). Recorded in the replay log
      conceptually but no substrate write happens here.
    - ``rejected_atoms``: each entry may include a ``warrant_defensibility``
      field. ``"contested"`` raises a CR-7 clarification.
    - ``clarifications``: verbatim auditor clarifications; written via
      :meth:`Substrate.add_clarification`.
    """
    # Auditor outputs need a source_id to route writes; the auditor's
    # prompt should always include one. Look in top-level OR in each
    # rejected/clarification entry, falling back to a sentinel.
    top_source_id = _coerce_optional_str(payload.get("source_id"))

    for raw_reject in _as_list(payload.get("rejected_atoms")):
        if not isinstance(raw_reject, dict):
            continue
        rej_dict: dict[str, Any] = cast("dict[str, Any]", raw_reject)
        source_id = _coerce_optional_str(rej_dict.get("source_id")) or top_source_id or "workspace"
        atom_id_ref = _coerce_optional_str(rej_dict.get("atom_id")) or "(unknown)"
        reason = str(rej_dict.get("reason", "(no reason)"))
        if rej_dict.get("warrant_defensibility") == "contested":
            clar_id = _raise_clarification(
                substrate=substrate,
                source_id=source_id,
                question=(
                    f"Auditor rejected atom {atom_id_ref} on "
                    f"warrant-defensibility grounds: {reason!r}. "
                    "Reaffirm, narrow, or reject?"
                ),
                context_refs=[atom_id_ref],
                options=["reaffirm", "narrow", "reject"],
                activity=_KIND_WARRANT_CONTESTED,
                identifier="auditor",
                role="auditor",
            )
            result.clarifications_raised.append(clar_id)

    for raw_clar in _as_list(payload.get("clarifications")):
        if not isinstance(raw_clar, dict):
            continue
        clar_dict: dict[str, Any] = cast("dict[str, Any]", raw_clar)
        source_id = _coerce_optional_str(clar_dict.get("source_id")) or top_source_id or "workspace"
        question = str(clar_dict.get("question", "(no question)"))
        raised_against = _coerce_optional_str(clar_dict.get("raised_against_atom_id"))
        options_raw = clar_dict.get("options") or []
        options = (
            [str(o) for o in cast("list[Any]", options_raw)]
            if isinstance(options_raw, list)
            else None
        )
        clar_id = _raise_clarification(
            substrate=substrate,
            source_id=source_id,
            question=question,
            context_refs=[raised_against] if raised_against else [],
            options=options,
            activity="auditor-clarification",
            identifier="auditor",
            role="auditor",
        )
        result.clarifications_raised.append(clar_id)


# --- Map-resolve path --------------------------------------------------


def _process_map_resolve_output(
    *,
    payload: dict[str, Any],
    inputs_hash: str,
    substrate: Substrate,
    workspace_root: Path,
    result: ReconcileResult,
) -> None:
    """Reconcile one map-resolve output payload.

    The resolver's ``proposals.yaml`` (surfaced here as ``payload``) carries:

    - ``proposed_entities``: list of entity dicts.
    - ``proposed_resolutions``: list of resolution dicts, each with an
      ``entity_index`` back-ref into the ``proposed_entities`` list.

    Each entity is written to ``mappings/entities/`` via
    :meth:`Substrate.add_entity`; each resolution to
    ``mappings/resolutions/`` via :meth:`Substrate.add_resolution`. A
    single mappings-scope replay-log entry is appended recording every
    path written.

    Empty lists produce no substrate writes and a ``substrate_changes: []``
    replay-log entry (SC-7 / R14 no-op contract).
    """
    proposed_entities = _as_list(payload.get("proposed_entities"))
    proposed_resolutions = _as_list(payload.get("proposed_resolutions"))
    substrate_changes: list[str] = []

    # Build committed entities list (index → entity id) for resolution
    # back-references.
    committed_entity_ids: list[str] = []
    now = datetime.now(UTC)

    for raw_entity in proposed_entities:
        if not isinstance(raw_entity, dict):
            committed_entity_ids.append("")
            continue
        entity_dict: dict[str, Any] = cast("dict[str, Any]", raw_entity)
        try:
            entity, prov = _build_entity(
                entity_dict, activity="map-resolve", inputs_hash=inputs_hash, now=now
            )
        except (ValueError, KeyError) as exc:
            result.errors.append(
                (Path("(in-memory-entity)"), f"entity-build failed: {exc}"),
            )
            committed_entity_ids.append("")
            continue
        # Write prov to mappings/provenance/.
        prov_path = substrate.mappings_provenance_path(prov.id)
        from amanuensis.fs._atomic import atomic_write_text
        from amanuensis.fs._serialize import serialize_yaml

        atomic_write_text(prov_path, serialize_yaml(prov))
        substrate_changes.append(str(prov_path.relative_to(workspace_root)))
        # Write entity (idempotent; immutable).
        substrate.add_entity(entity)
        committed_entity_ids.append(entity.id)
        entity_path = substrate.entity_path(entity.id)
        substrate_changes.append(str(entity_path.relative_to(workspace_root)))

    for raw_res in proposed_resolutions:
        if not isinstance(raw_res, dict):
            continue
        res_dict: dict[str, Any] = cast("dict[str, Any]", raw_res)
        entity_index = res_dict.get("entity_index")
        if (
            not isinstance(entity_index, int)
            or entity_index < 0
            or entity_index >= len(committed_entity_ids)
        ):
            result.errors.append(
                (Path("(in-memory-resolution)"), f"entity_index {entity_index!r} out of range"),
            )
            continue
        entity_id = committed_entity_ids[entity_index]
        if not entity_id:
            # The entity failed to build; skip this resolution.
            continue
        try:
            resolution, prov = _build_resolution(
                res_dict,
                entity_id=entity_id,
                activity="map-resolve",
                inputs_hash=inputs_hash,
                now=now,
            )
        except (ValueError, KeyError) as exc:
            result.errors.append(
                (Path("(in-memory-resolution)"), f"resolution-build failed: {exc}"),
            )
            continue
        from amanuensis.fs._atomic import atomic_write_text
        from amanuensis.fs._serialize import serialize_yaml

        prov_path = substrate.mappings_provenance_path(prov.id)
        atomic_write_text(prov_path, serialize_yaml(prov))
        substrate_changes.append(str(prov_path.relative_to(workspace_root)))
        substrate.add_resolution(resolution)
        res_path = substrate.resolution_path(resolution.id)
        substrate_changes.append(str(res_path.relative_to(workspace_root)))

    _append_mappings_replay(
        workspace_root=workspace_root,
        inputs_hash=inputs_hash,
        substrate_changes=substrate_changes,
        activity="map-resolve",
    )


def _stable_role_attribution_at(inputs_hash: str) -> datetime:
    """Return a deterministic ``at`` timestamp derived from ``inputs_hash``.

    Used so the role_attribution carried inside content-addressable
    Entity / Resolution records is stable across re-runs of the same
    resolver output (otherwise ``datetime.now()`` flips content hashes
    and the second reconcile trips INV-14's duplicate-triple guard).

    Maps the first 8 hex/word chars of the hash into a fixed two-year
    window starting at 2026-01-01 UTC. The exact value is opaque — only
    its determinism per ``inputs_hash`` matters.
    """
    base = datetime(2026, 1, 1, tzinfo=UTC)
    h = hashlib.sha256(inputs_hash.encode("utf-8")).hexdigest()
    offset_seconds = int(h[:8], 16) % (2 * 365 * 24 * 3600)
    return base + timedelta(seconds=offset_seconds)


def _build_entity(
    raw: dict[str, Any],
    *,
    activity: str,
    inputs_hash: str,
    now: datetime,
) -> tuple[Entity, ProvenanceRecord]:
    """Construct an Entity + its ProvenanceRecord from a resolver proposal.

    The role-attribution ``at`` is derived deterministically from
    ``inputs_hash`` so re-running the same resolver output produces the
    same content-addressable Entity id (idempotency contract). The
    ProvenanceRecord still uses real wall-clock ``now`` — prov records
    are a log of what actually happened, not part of entity identity.
    """
    stable_at = _stable_role_attribution_at(inputs_hash)
    role_attribution = RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="map-resolve", role="map-resolve"),
        activity="proposed",
        at=stable_at,
    )
    entity_draft = Entity(
        id="e-" + "0" * 16,
        kind=str(raw.get("kind", "")),
        canonical_name=str(raw.get("canonical_name", "")),
        aliases=[str(a) for a in _as_list(raw.get("aliases"))],
        notes=_coerce_optional_str(raw.get("notes")),
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    entity_id = compute_id(entity_draft)
    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="entity",
        entity_id=entity_id,
        activity=activity,
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=[],
        was_attributed_to=AgentAttribution(
            kind="llm", identifier="map-resolve", role="map-resolve"
        ),
        was_influenced_by=[inputs_hash] if inputs_hash else [],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = prov_draft.model_copy(update={"id": prov_id})
    entity = entity_draft.model_copy(update={"id": entity_id, "provenance_id": prov_id})
    return entity, prov


def _build_resolution(
    raw: dict[str, Any],
    *,
    entity_id: str,
    activity: str,
    inputs_hash: str,
    now: datetime,
) -> tuple[Resolution, ProvenanceRecord]:
    """Construct a Resolution + its ProvenanceRecord from a resolver proposal."""
    confidence_raw = raw.get("confidence", "medium")
    if confidence_raw not in {"high", "medium", "low"}:
        raise ValueError(f"confidence {confidence_raw!r} not in closed set")
    confidence_lit = cast("Literal['high', 'medium', 'low']", confidence_raw)

    stable_at = _stable_role_attribution_at(inputs_hash)
    role_attribution = RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="map-resolve", role="map-resolve"),
        activity="proposed",
        at=stable_at,
    )
    resolution_draft = Resolution(
        id="j-" + "0" * 16,
        source_id=str(raw.get("source_id", "")),
        atom_id=str(raw.get("atom_id", "")),
        operand_index=int(raw.get("operand_index", 0)),
        entity_id=entity_id,
        confidence=confidence_lit,
        basis=str(raw.get("basis", "map-resolve proposal")),
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    resolution_id = compute_id(resolution_draft)
    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="resolution",
        entity_id=resolution_id,
        activity=activity,
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=[entity_id],
        was_attributed_to=AgentAttribution(
            kind="llm", identifier="map-resolve", role="map-resolve"
        ),
        was_influenced_by=[inputs_hash] if inputs_hash else [],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = prov_draft.model_copy(update={"id": prov_id})
    resolution = resolution_draft.model_copy(update={"id": resolution_id, "provenance_id": prov_id})
    return resolution, prov


# --- Phase 2b M4: CrossDocRelation reconciliation ----------------------
#
# ``_build_cross_doc_relation`` is the choke point the Phase 2b connect-role
# reconciler (M5, ``_process_connect_output`` below) calls per candidate.
# It is also exercised directly by ``tests/dispatch/test_cross_doc_reconcile.py``.


@dataclass(slots=True)
class CrossDocBuildResult:
    """Outcome of one ``_build_cross_doc_relation`` call (Phase 2b cleanup-2).

    Exactly one of ``cross_doc_relation`` / ``clarification_id`` is
    populated on the non-error paths:

    - ``cross_doc_relation`` set, ``clarification_id`` None — the
      candidate satisfied INV-15 and was committed.
    - ``cross_doc_relation`` None, ``clarification_id`` set — INV-15
      rejected the candidate and the helper auto-raised a
      ``resolution-ambiguous`` Clarification under the from-endpoint
      distillation. ``clarification_id`` is the id of that record.

    The Phase 2b ship recovered the auto-raised id by mtime-scanning
    ``clarifications/open/`` after the call. That works for one
    candidate per drain but is brittle when two candidates from the
    same from_source raise clarifications within the same mtime tick
    (1s precision on macOS HFS+). cleanup-2 plumbs the id back
    directly so the reconciler does not have to guess.
    """

    cross_doc_relation: CrossDocRelation | None = None
    clarification_id: str | None = None


def _build_cross_doc_relation(
    candidate: dict[str, Any],
    substrate: Substrate,
    prov: ProvenanceRecord,
    role_attributions: list[RoleAttribution],
) -> CrossDocBuildResult:
    """Build a ``CrossDocRelation`` from a Connector-role candidate dict.

    Mirrors :func:`_build_resolution` (Phase 2a) for the validation +
    write pattern, with one Phase 2b twist: INV-15 failures at the
    substrate layer are NOT propagated as exceptions. Instead, the gate's
    ``SharedEntityGateViolation`` is converted into an open
    ``resolution-ambiguous`` Clarification raised under the from-endpoint
    distillation, and the function returns ``None``. The Connector role
    cannot itself add Resolutions, so the only sanctioned recovery path
    is for a supervisor to land the missing join (then a subsequent
    reconcile retry commits the edge — see T4.4).

    Args:
        candidate: Raw Connector output payload. Expected keys are the
            ``CrossDocRelation`` fields excluding ``id``,
            ``provenance_id``, ``role_attributions``, and
            ``schema_version`` (those are stamped by this function).
        substrate: Bound substrate handle. Used both for the INV-15
            gate (via ``add_cross_doc_relation``) and for the
            clarification raise (via ``add_clarification``).
        prov: A pre-built ``ProvenanceRecord`` whose ``id`` will be
            stamped on the relation's ``provenance_id`` field and (on
            INV-15 failure) on the clarification's
            ``raised_provenance_id``. The caller persists this record;
            this function does NOT call ``add_provenance``.
        role_attributions: Attribution audit trail attached to the
            relation. The same list is forwarded onto the clarification
            on the rejection path so the auditor trail stays unified.

    Returns:
        A :class:`CrossDocBuildResult` carrying either the committed
        ``CrossDocRelation`` (happy path) or the id of the auto-raised
        ``resolution-ambiguous`` Clarification (INV-15 rejection path).
        Phase 2b cleanup-2 replaced the prior ``CrossDocRelation | None``
        return so the reconciler no longer has to mtime-scan
        ``clarifications/open/`` to recover the clarification id.

    Raises:
        CandidateShapeError: The candidate dict cannot be coerced into
            a valid ``CrossDocRelation`` (pydantic validation failure)
            OR the candidate names ``from_source_id == to_source_id``
            (Connector should not propose intra-source edges; this is
            shape, not state).
        MutationOfImmutableRecord: A divergent-content collision on the
            relation id. Idempotent re-writes of byte-identical content
            are absorbed by the substrate; only real corruption gets
            here.
    """
    # Stage 1: pydantic shape check. The candidate is model-produced YAML
    # and may legitimately be malformed — catch ValidationError and
    # re-raise as CandidateShapeError so the dispatch driver can route
    # it into ``ReconcileResult.errors`` without conflating it with the
    # other typed-error paths.
    try:
        rel_draft = CrossDocRelation(
            id="x-" + "0" * 16,
            from_atom_id=str(candidate["from_atom_id"]),
            from_source_id=str(candidate["from_source_id"]),
            to_atom_id=str(candidate["to_atom_id"]),
            to_source_id=str(candidate["to_source_id"]),
            kind=candidate["kind"],
            warrant=str(candidate["warrant"]),
            warrant_defensibility=candidate["warrant_defensibility"],
            warrant_basis=str(candidate["warrant_basis"]),
            confidence=candidate["confidence"],
            shared_entities=[str(e) for e in candidate.get("shared_entities", [])],
            provenance_id=prov.id,
            role_attributions=list(role_attributions),
            schema_version=1,
        )
    except (ValidationError, KeyError, TypeError) as exc:
        raise CandidateShapeError(f"Connector candidate failed shape validation: {exc}") from exc

    # Stage 2: stamp the real content-addressable id.
    rel_id = compute_id(rel_draft)
    rel = rel_draft.model_copy(update={"id": rel_id})

    # Stage 3: hand to the substrate. The substrate enforces the
    # cross-source constraint, the INV-15 shared-entity gate, id
    # discipline, and INV-13 immutability — handle each typed failure
    # per its semantic class.
    try:
        substrate.add_cross_doc_relation(rel)
    except SharedEntityGateViolation:
        # INV-15: ambiguous substrate state. Surface as a clarification
        # for human supervision; do NOT propagate. Phase 2b cleanup-2:
        # capture the clarification id from the helper rather than
        # leaving the caller to mtime-scan to recover it.
        clar_id = _auto_raise_resolution_clarification(
            rel,
            substrate=substrate,
            prov=prov,
            role_attributions=role_attributions,
        )
        return CrossDocBuildResult(cross_doc_relation=None, clarification_id=clar_id)
    except CrossSourceConstraintViolation as exc:
        # The Connector should never propose intra-source edges — they
        # belong to the Phase 1 extractor surface. Treat this as a shape
        # violation rather than a clarification-worthy ambiguity.
        raise CandidateShapeError(
            f"Connector proposed intra-source edge (from_source_id == to_source_id "
            f"== {rel.from_source_id!r}); cross-doc relations must span two "
            "distinct distillations"
        ) from exc
    # MutationOfImmutableRecord propagates as-is: idempotent re-writes
    # are absorbed by add_cross_doc_relation itself, so a raised
    # immutability error indicates real corruption (divergent content on
    # an existing id) which a clarification cannot fix.

    return CrossDocBuildResult(cross_doc_relation=rel, clarification_id=None)


def _auto_raise_resolution_clarification(
    rel: CrossDocRelation,
    *,
    substrate: Substrate,
    prov: ProvenanceRecord,
    role_attributions: list[RoleAttribution],
) -> str:
    """Auto-raise a ``resolution-ambiguous`` clarification for a rejected edge.

    Called by :func:`_build_cross_doc_relation` when the INV-15 gate
    rejects a candidate. The clarification is filed under the
    from-endpoint's distillation (``rel.from_source_id``) so a
    supervisor browsing one source's open queue sees the edge proposal
    without having to cross-reference the to-endpoint.

    Returns:
        The id of the Clarification that was written. Phase 2b
        cleanup-2: the caller uses this id to record the raise in
        ``ReconcileResult.clarifications_raised`` without scanning the
        open-clarifications directory.

    Notes:
        - The clarification's ``raised_provenance_id`` is the SAME
          provenance record the caller already minted for the relation
          attempt. We do NOT call ``substrate.add_provenance(prov)``
          here — the caller is responsible for that. M4's reconciler
          path lives entirely under the workspace flock so a partial
          write cannot leak.
        - ``context_refs`` carries every referenced atom AND every
          shared entity so a human navigator can pivot to any of them
          from the resolved-clarification view (M8 / web UI).
        - ``raised_by_activity`` is a Phase-2b-specific string
          (``"connect-resolution-ambiguous"``) so per-activity
          dashboards can distinguish Connector-raised items from the
          Phase 2a map-audit path that also uses the
          ``resolution-ambiguous`` kind.
    """
    now = datetime.now(UTC)
    # Use the first role-attribution's agent as the "raised_by" agent —
    # if the Connector's attribution list is empty (it shouldn't be, but
    # defensively) fall back to a synthetic LLM stamp.
    if role_attributions:
        raised_by = role_attributions[0].agent
    else:
        raised_by = AgentAttribution(kind="llm", identifier="connect", role="connect")

    # Build the context_refs list: both atoms (formatted as
    # ``a:<source>:<atom>`` for navigability) plus every shared entity.
    context_refs: list[str] = [
        f"a:{rel.from_source_id}:{rel.from_atom_id}",
        f"a:{rel.to_source_id}:{rel.to_atom_id}",
    ]
    for entity_id in rel.shared_entities:
        context_refs.append(f"e:{entity_id}")

    # Question text doubles as the human-readable body (the Clarification
    # schema collapses body+question into one ``question`` field).
    shared_entities_listing = ", ".join(rel.shared_entities) if rel.shared_entities else "(none)"
    question = (
        f"The Connector role proposed a cross-doc edge between atoms "
        f"`{rel.from_atom_id}` (in `{rel.from_source_id}`) and "
        f"`{rel.to_atom_id}` (in `{rel.to_source_id}`), referencing "
        f"shared entities: {shared_entities_listing}. However, one or "
        "both endpoints do not have Resolution records pointing to "
        "these entities.\n\n"
        "Resolve by either:\n"
        "- Adding the missing Resolution(s) via `amanuensis map resolve` "
        "for the unresolved endpoint, OR\n"
        "- Marking this edge as a false positive (no action; Connector "
        "will not retry the same candidate due to content-addressable "
        "caching unless inputs change)."
    )

    clar_draft = Clarification(
        id="c-" + "0" * 16,
        status="open",
        kind="resolution-ambiguous",
        raised_at=now,
        raised_by=raised_by,
        raised_by_activity=_KIND_CONNECT_RESOLUTION_AMBIGUOUS,
        context_refs=context_refs,
        question=question,
        options=None,
        resolved_at=None,
        resolved_by=None,
        resolution=None,
        raised_provenance_id=prov.id,
        resolved_provenance_id=None,
        schema_version=2,
    )
    clar_id = compute_id(clar_draft)
    clar = clar_draft.model_copy(update={"id": clar_id})
    substrate.add_clarification(rel.from_source_id, clar)
    return clar_id


# --- Phase 2b M5: Connector output reconciliation ----------------------


def _process_connect_output(
    *,
    payload: dict[str, Any],
    inputs_hash: str,
    substrate: Substrate,
    workspace_root: Path,
    result: ReconcileResult,
) -> None:
    """Reconcile one Connector-role output payload.

    The Connector emits a top-level ``proposed_relations`` list whose
    entries are candidate ``CrossDocRelation`` dicts (id-less,
    provenance-less). Each candidate is routed through
    :func:`_build_cross_doc_relation`, which:

    - Builds + validates the typed record (raises
      :class:`CandidateShapeError` on shape failures, which we record in
      ``result.errors`` and skip).
    - Runs the INV-15 shared-entity gate. INV-15 failures are NOT
      propagated: the helper auto-raises a ``resolution-ambiguous``
      Clarification under the from-endpoint distillation and returns
      ``None``. We record the clarification id in
      ``result.clarifications_raised`` so the operator sees both the
      raise and the (still-pending) candidate in one summary.
    - On a clean candidate the typed record is written to
      ``mappings/relations/`` via :meth:`Substrate.add_cross_doc_relation`,
      and we record the id in ``result.relations_committed``.

    A single PROV record covers the entire output payload (the M5
    activity is "one Connector call → one PROV record" — fine-grained
    per-candidate PROV is M6/M7 territory). The PROV record's
    ``used_entity_ids`` lists every from/to atom referenced; its
    ``activity`` is ``connect-reconcile``.

    The replay-log append at the end is mappings-scoped (mirrors
    map-resolve / map-audit) so the dispatch-loop's append-once
    discipline is preserved.
    """
    from amanuensis.fs._atomic import atomic_write_text  # pyright: ignore[reportPrivateUsage]
    from amanuensis.fs._serialize import serialize_yaml  # pyright: ignore[reportPrivateUsage]

    proposed = _as_list(payload.get("proposed_relations"))
    substrate_changes: list[str] = []

    # Build the PROV record up-front so all candidates from this output
    # file share one canonical attribution. ``activity_started_at`` is a
    # stable timestamp derived from the inputs_hash (mirrors map-resolve's
    # convention) so content-addressable PROV ids are deterministic
    # across reconciler retries on the same output.
    started_at = _stable_role_attribution_at(inputs_hash)
    used_entity_ids: list[str] = []
    for raw in proposed:
        if not isinstance(raw, dict):
            continue
        from_atom = raw.get("from_atom_id")
        to_atom = raw.get("to_atom_id")
        if isinstance(from_atom, str):
            used_entity_ids.append(from_atom)
        if isinstance(to_atom, str):
            used_entity_ids.append(to_atom)

    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="cross-doc-relation",
        entity_id="x-placeholder",
        activity="connect-reconcile",
        activity_started_at=started_at,
        activity_ended_at=started_at,
        used_entity_ids=used_entity_ids,
        was_attributed_to=AgentAttribution(
            kind="llm",
            identifier="connect",
            role="connect",
        ),
        was_influenced_by=[inputs_hash] if inputs_hash else [],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = prov_draft.model_copy(update={"id": prov_id})

    # Write PROV to mappings/provenance/ first so any per-candidate
    # commit can point at it. The path is deterministic per id; a
    # repeated reconcile of the same output is a byte-identical re-write.
    prov_path = substrate.mappings_provenance_path(prov.id)
    atomic_write_text(prov_path, serialize_yaml(prov))
    substrate_changes.append(str(prov_path.relative_to(workspace_root)))

    role_attribution = RoleAttribution(
        agent=prov.was_attributed_to,
        activity="proposed",
        at=started_at,
    )

    for raw_candidate in proposed:
        if not isinstance(raw_candidate, dict):
            continue
        candidate: dict[str, Any] = cast("dict[str, Any]", raw_candidate)
        try:
            build = _build_cross_doc_relation(
                candidate,
                substrate,
                prov,
                role_attributions=[role_attribution],
            )
        except CandidateShapeError as exc:
            # Shape errors are recorded so the operator can triage; we
            # do NOT raise a clarification (the model output is malformed
            # in a way a human cannot meaningfully resolve other than by
            # re-running the role with a corrected prompt).
            result.errors.append((Path("(in-memory-cross-doc-relation)"), str(exc)))
            continue

        if build.cross_doc_relation is None:
            # INV-15 rejection path. ``_build_cross_doc_relation`` already
            # auto-raised the clarification under the from-endpoint
            # distillation and threaded its id back to us (Phase 2b
            # cleanup-2 replaced the prior mtime-scan recovery). Record
            # the id in ReconcileResult + add the clarification's path to
            # substrate_changes so the replay-log captures the boundary
            # crossing.
            clar_id = build.clarification_id
            if clar_id is not None:
                result.clarifications_raised.append(clar_id)
                from_source = _coerce_optional_str(candidate.get("from_source_id"))
                if from_source:
                    clar_path = (
                        substrate.root
                        / "distillations"
                        / from_source
                        / "clarifications"
                        / "open"
                        / f"{clar_id}.md"
                    )
                    if clar_path.is_file():
                        substrate_changes.append(str(clar_path.relative_to(workspace_root)))
            continue

        # Happy path: record the committed relation.
        rel = build.cross_doc_relation
        result.relations_committed.append(rel.id)
        rel_path = substrate.cross_doc_relation_path(rel.id)
        substrate_changes.append(str(rel_path.relative_to(workspace_root)))

    _append_mappings_replay(
        workspace_root=workspace_root,
        inputs_hash=inputs_hash,
        substrate_changes=substrate_changes,
        activity="connect-reconcile",
        actor_role="connect",
    )


def _append_mappings_replay(
    *,
    workspace_root: Path,
    inputs_hash: str,
    substrate_changes: list[str],
    activity: str,
    actor_role: Literal["map-resolve", "map-audit", "connect"] = "map-resolve",
) -> None:
    """Append a single replay-log entry to the mappings-scope log.

    ``actor_role`` defaults to ``"map-resolve"`` to preserve M7.4's
    contract for the map-resolve / map-audit reconcile paths. The
    Phase 2b M5 connect reconcile path passes ``actor_role="connect"``
    so the replay-log entry's actor matches the activity.
    """
    log = ReplayLog.for_mappings(workspace_root)
    log.append(
        actor=AgentAttribution(kind="llm", identifier="reconcile", role=actor_role),
        activity=activity,
        inputs_hash=inputs_hash,
        outputs_hash=inputs_hash,
        cache_hit=False,
        substrate_changes=substrate_changes,
        duration_seconds=0.0,
        _lock_held=True,  # reconcile_outputs already holds the workspace flock
    )


# --- Map-audit path ----------------------------------------------------


def _process_map_audit_output(
    *,
    payload: dict[str, Any],
    substrate: Substrate,
    workspace_root: Path,
    result: ReconcileResult,
) -> None:
    """Reconcile one map-audit output payload.

    The auditor's ``decisions.yaml`` (surfaced here as ``payload``) carries:

    - ``accepted_entities``: list of entity ids confirmed by the auditor.
    - ``accepted_resolutions``: list of resolution ids confirmed.
    - ``rejected_entities``: list of entity ids the auditor rejected.
    - ``rejected_resolutions``: list of resolution ids the auditor rejected.
    - ``clarifications``: list of dicts with ``kind``, ``source_id``, and
      optionally ``context_refs`` / ``question``.

    Cross-check: every accepted id must exist in the substrate. Unknown ids
    are appended to ``result.errors``. Clarifications are written under
    ``distillations/<source_id>/clarifications/open/`` via
    :meth:`Substrate.add_clarification`.
    """
    accepted_entities = _as_list(payload.get("accepted_entities"))
    accepted_resolutions = _as_list(payload.get("accepted_resolutions"))
    substrate_changes: list[str] = []
    inputs_hash = _coerce_optional_str(payload.get("inputs_hash")) or ""

    # Cross-check accepted entity ids.
    for raw_id in accepted_entities:
        entity_id = str(raw_id) if raw_id is not None else ""
        if not entity_id:
            continue
        entity_path = substrate.entity_path(entity_id)
        if not entity_path.is_file():
            result.errors.append(
                (entity_path, f"accepted_entity {entity_id!r} not found in substrate"),
            )

    # Cross-check accepted resolution ids.
    for raw_id in accepted_resolutions:
        resolution_id = str(raw_id) if raw_id is not None else ""
        if not resolution_id:
            continue
        resolution_path = substrate.resolution_path(resolution_id)
        if not resolution_path.is_file():
            result.errors.append(
                (resolution_path, f"accepted_resolution {resolution_id!r} not found in substrate"),
            )

    # Process clarifications.
    for raw_clar in _as_list(payload.get("clarifications")):
        if not isinstance(raw_clar, dict):
            continue
        clar_dict: dict[str, Any] = cast("dict[str, Any]", raw_clar)
        kind_raw = clar_dict.get("kind", "resolution-disputed")
        if kind_raw not in {
            "resolution-disputed",
            "resolution-ambiguous",
            "warrant-defensibility-contested",
        }:
            kind_raw = "resolution-disputed"
        clar_kind = cast(
            "Literal['warrant-defensibility-contested', 'resolution-disputed', 'resolution-ambiguous']",  # noqa: E501
            kind_raw,
        )
        source_id = _coerce_optional_str(clar_dict.get("source_id")) or "workspace"
        context_refs = [str(r) for r in _as_list(clar_dict.get("context_refs"))]
        question = str(clar_dict.get("question", "(no question)"))
        now = datetime.now(UTC)
        raised_by = AgentAttribution(kind="llm", identifier="map-audit", role="map-audit")

        clar_draft = Clarification(
            id="c-" + "0" * 16,
            status="open",
            kind=clar_kind,
            raised_at=now,
            raised_by=raised_by,
            raised_by_activity="map-audit",
            context_refs=context_refs,
            question=question,
            options=None,
            resolved_at=None,
            resolved_by=None,
            resolution=None,
            raised_provenance_id="p-" + "0" * 16,
            resolved_provenance_id=None,
            schema_version=2,
        )
        clar_id = compute_id(clar_draft)
        prov_draft = ProvenanceRecord(
            id="p-" + "0" * 16,
            entity_type="clarification-raised",
            entity_id=clar_id,
            activity="map-audit",
            activity_started_at=now,
            activity_ended_at=now,
            used_entity_ids=context_refs,
            was_attributed_to=raised_by,
            was_influenced_by=[],
            schema_version=1,
        )
        prov_id = compute_id(prov_draft)
        prov = prov_draft.model_copy(update={"id": prov_id})
        substrate.add_provenance(source_id, prov)
        clar = clar_draft.model_copy(update={"id": clar_id, "raised_provenance_id": prov_id})
        substrate.add_clarification(source_id, clar)
        clar_path = substrate.clarification_path(source_id, clar_id, resolved=False)
        substrate_changes.append(str(clar_path.relative_to(workspace_root)))
        result.clarifications_raised.append(clar_id)

    _append_mappings_replay(
        workspace_root=workspace_root,
        inputs_hash=inputs_hash,
        substrate_changes=substrate_changes,
        activity="map-audit",
    )


# --- Clarification raising ---------------------------------------------


def _raise_clarification(
    *,
    substrate: Substrate,
    source_id: str,
    question: str,
    context_refs: list[str],
    options: list[str] | None,
    activity: str,
    identifier: str,
    role: Literal["extractor", "auditor", "human_supervisor"],
) -> str:
    """Build + persist one open clarification and its raised PROV record.

    Returns the persisted clarification id. The clarification's id is
    content-addressable; the raised PROV record's entity_id == the
    clarification id. ``raised_provenance_id`` is volatile for the
    clarification's hash, so the id is stable across the placeholder /
    final ``model_copy`` step.
    """
    now = datetime.now(UTC)
    raised_by = AgentAttribution(kind="llm", identifier=identifier, role=role)

    # Every Phase 1 clarification (warrant-contested, atom-validation-failed,
    # any future auditor surface) is an extraction-time quality issue, so the
    # kind discriminator is always "warrant-defensibility-contested". The
    # other two kinds ("resolution-disputed", "resolution-ambiguous") are
    # MAP-phase clarifications that get raised by T6.3 / T6.4's reconcilers,
    # not from this Phase 1 path.
    _clar_kind: Literal[
        "warrant-defensibility-contested",
        "resolution-disputed",
        "resolution-ambiguous",
    ] = "warrant-defensibility-contested"

    clar_draft = Clarification(
        id="c-" + "0" * 16,
        status="open",
        kind=_clar_kind,
        raised_at=now,
        raised_by=raised_by,
        raised_by_activity=activity,
        context_refs=list(context_refs),
        question=question,
        options=options,
        resolved_at=None,
        resolved_by=None,
        resolution=None,
        raised_provenance_id="p-" + "0" * 16,
        resolved_provenance_id=None,
        schema_version=2,
    )
    clar_id = compute_id(clar_draft)

    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="clarification-raised",
        entity_id=clar_id,
        activity=activity,
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=list(context_refs),
        was_attributed_to=raised_by,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = prov_draft.model_copy(update={"id": prov_id})
    substrate.add_provenance(source_id, prov)

    clar = clar_draft.model_copy(update={"id": clar_id, "raised_provenance_id": prov_id})
    substrate.add_clarification(source_id, clar)
    return clar_id


# --- Coercion helpers --------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    """Return ``value`` if it's a list; else an empty list (defensive parse)."""
    if isinstance(value, list):
        return cast("list[Any]", value)
    return []


def _coerce_optional_str(value: Any) -> str | None:
    """Coerce to ``str | None`` (empty strings collapse to None)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)
