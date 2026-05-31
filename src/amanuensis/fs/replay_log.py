"""Append-only replay log with monotonic seq counter (distillation or mapping scope).

The replay log is the canonical activity stream for a distillation or the
mappings layer: every role invocation, every cache hit, every substrate
mutation lands as one ``ReplayLogEntry`` YAML file. Entries are ordered by a
workspace-wide-serialized integer ``seq`` and grouped into day subdirectories
for human navigation.

Layout (plan §5; see also M1.6 substrate layout)::

    <workspace>/
      amanuensis.yaml                                    (INV-1 marker)

      # Distillation scope (Phase 1 roles):
      distillations/<source-id>/
        replay-log/
          .next-seq                              (one decimal integer; default 0)
          <yyyy-mm-dd>/<padded-seq-12>.yaml      (one ReplayLogEntry per file)

      # Mapping scope (Phase 2a roles):
      mappings/
        replay-log/
          .next-seq
          <yyyy-mm-dd>/<padded-seq-12>.yaml

The ``.next-seq`` counter is per-scope (each distillation or the mappings
layer gets its own), but the workspace-level ``flock`` from
``amanuensis.fs.lock.acquire_workspace_lock`` serializes ALL writers
across the workspace — so two writers targeting different scopes still take
the same lock. Cheap, correct, and matches the plan §5 concurrency model
("workspace flock").

Crash discipline (plan §5):

1. Acquire workspace flock.
2. Read ``.next-seq`` (default 0 if missing).
3. Scan all day subdirectories for any stale ``<seq:012d>.yaml`` that
   differs from the path we are about to write; unlink each.
4. Write the entry file at seq ``N`` atomically (write-to-tmp-then-rename).
5. Write the new ``.next-seq`` value (``N+1``) atomically.
6. Release flock.

A crash between steps 4 and 5 leaves the counter at ``N``. The next
writer reads ``N``, overwrites the orphan entry at seq ``N`` with its
own content, and increments to ``N+1``. Net result: no gap, no
duplicate, no observable inconsistency on retry. ``atomic_write_text``
(M1.6) guarantees no torn writes at either step.

Cross-day orphan window: a crash near UTC midnight can leave the orphan
in day ``D`` while the recovery writer's timestamp falls in day ``D+1``.
``atomic_write_text`` writes to the *new* day directory and would never
notice the stale file in the *old* day directory — leaving two files
with the same seq, in different days, violating plan §5's "no
duplicates" promise. Step 3 above (the scan-and-unlink) closes that
window. Cost is O(num_day_dirs) per append (one ``iterdir`` plus N
unlinks), negligible for Phase 1 substrate sizes.

Read paths (``read_seq``, ``list_entries``, ``get_entry``) do NOT
acquire the workspace lock — plan §5 reserves the lock for mutating
operations. ``os.replace`` (M1.6) gives readers consistent snapshots.

API:
    ``ReplayLog.for_source(workspace_root, source_id)`` — bind to a distillation.
    ``ReplayLog.for_mappings(workspace_root)`` — bind to the mappings scope.
    ``append(...)`` — assign seq + write the entry (mutating).
    ``read_seq()`` — current counter value (lock-free).
    ``list_entries()`` — iterate entries in seq order (lock-free).
    ``get_entry(seq)`` — look up by seq (lock-free).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from amanuensis.schemas import AgentAttribution, ReplayLogEntry

from ._atomic import atomic_write_text
from ._errors import SubstrateMarkerMissing, SubstrateNotFound
from ._serialize import (
    _safe_dump,  # pyright: ignore[reportPrivateUsage] — package-internal helper
    _safe_load,  # pyright: ignore[reportPrivateUsage] — package-internal helper
)
from .lock import DEFAULT_TIMEOUT_SECONDS, acquire_workspace_lock
from .substrate import (
    _validate_id_component,  # pyright: ignore[reportPrivateUsage] — package-internal helper
)

_MARKER_FILENAME: str = "amanuensis.yaml"  # mirrors Substrate.MARKER_FILENAME
_COUNTER_FILENAME: str = ".next-seq"
_SEQ_WIDTH: int = 12  # zero-padded width-12 per plan §5 (e.g. 000000000042.yaml)

# Roles that route to <workspace>/mappings/replay-log/.
_MAP_ROLES: frozenset[str] = frozenset({"map-resolve", "map-audit"})

# Roles that route to <workspace>/distillations/<source-id>/replay-log/.
_DISTILLATION_ROLES: frozenset[str] = frozenset(
    {"extractor", "auditor", "contrarian", "constructive", "premortem", "human_supervisor"}
)


def _resolve_replay_log_root(  # pyright: ignore[reportUnusedFunction] — package-internal helper used by tests and future dispatch wiring
    workspace_root: Path, role: str, source_id: str | None
) -> Path:
    """Compute the replay-log directory for a given role + optional source.

    Map roles (map-resolve, map-audit) ignore source_id and route to
    ``<workspace>/mappings/replay-log/``. Distillation roles (extractor,
    auditor, contrarian, constructive, premortem, human_supervisor)
    require source_id and route to
    ``<workspace>/distillations/<source>/replay-log/``.

    Args:
        workspace_root: Resolved workspace root Path (must be a directory
            containing the INV-1 marker; validated by the caller).
        role: Role name string. Determines routing branch.
        source_id: Per-distillation scope key. Required for distillation
            roles; ignored (may be None) for map roles.

    Returns:
        The absolute Path to the replay-log directory for this scope.

    Raises:
        ValueError: if a distillation role is given without source_id.
    """
    if role in _MAP_ROLES:
        return workspace_root / "mappings" / "replay-log"
    # All other roles (including distillation roles and any unknown
    # future role) route through the per-distillation path. This keeps
    # the helper forward-compatible without requiring exhaustive
    # enumeration of every possible role name.
    if source_id is None:
        raise ValueError(f"role {role!r} requires source_id but source_id is None")
    return workspace_root / "distillations" / source_id / "replay-log"


class ReplayLog:
    """Append-only replay log bound to a workspace scope (distillation or mappings).

    Construction validates the workspace marker (INV-1). For distillation
    scope, the ``source_id`` path component is also validated. The replay
    log directory is created lazily on first append.

    Prefer the factory classmethods over direct construction:
    - ``ReplayLog.for_source(workspace_root, source_id)`` — Phase 1 distillation scope.
    - ``ReplayLog.for_mappings(workspace_root)`` — Phase 2a mappings scope.

    Concurrency: ``append`` holds the workspace flock for the entire
    read-counter / write-entry / bump-counter cycle. Read methods are
    lock-free per plan §5.

    Crash discipline: see module docstring. A crashed writer leaves a
    recoverable state — the next writer's append overwrites any orphan
    entry at the unclaimed seq and bumps the counter, producing a
    gap-free sequence on retry.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        source_id: str,
        *,
        _kind: Literal["distillation", "mapping"] = "distillation",
    ) -> None:
        """Bind to a workspace scope.

        Direct construction with positional args is the backward-compat
        path for distillation scope (matches the old ``ReplayLog(root, src)``
        signature). Prefer the factory classmethods for new call sites.

        Args:
            workspace_root: Workspace root directory containing amanuensis.yaml.
            source_id: Per-distillation scope key (validated for distillation
                kind; ignored for mapping kind — pass any string placeholder).
            _kind: Internal discriminator. ``"distillation"`` routes to
                ``distillations/<source_id>/replay-log/``;
                ``"mapping"`` routes to ``mappings/replay-log/``.
        """
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise SubstrateMarkerMissing(f"workspace_root {root} is not an existing directory.")
        marker = root / _MARKER_FILENAME
        if not marker.is_file():
            raise SubstrateMarkerMissing(
                f"amanuensis.yaml marker missing at {root}; "
                "refusing to open a replay log on a non-workspace directory."
            )
        if _kind == "distillation":
            _validate_id_component(source_id, label="source_id")
        self.workspace_root: Path = root
        self.source_id: str = source_id
        self._kind: Literal["distillation", "mapping"] = _kind

    # --- Factory classmethods ------------------------------------------

    @classmethod
    def for_source(cls, workspace_root: Path | str, source_id: str) -> ReplayLog:
        """Bind to a per-distillation replay log (Phase 1 backward-compat factory).

        Args:
            workspace_root: Workspace root directory containing amanuensis.yaml.
            source_id: Distillation scope key. Validated as a safe path component.

        Returns:
            A ``ReplayLog`` scoped to
            ``<workspace>/distillations/<source_id>/replay-log/``.
        """
        return cls(workspace_root, source_id, _kind="distillation")

    @classmethod
    def for_mappings(cls, workspace_root: Path | str) -> ReplayLog:
        """Bind to the workspace-level mappings replay log (Phase 2a factory).

        The mappings scope is workspace-global — there is no per-source
        partition. The ``source_id`` stored internally is the empty string
        (not used for path construction in mapping kind).

        Args:
            workspace_root: Workspace root directory containing amanuensis.yaml.

        Returns:
            A ``ReplayLog`` scoped to ``<workspace>/mappings/replay-log/``.
        """
        return cls(workspace_root, "", _kind="mapping")

    # --- Path resolvers (pure path computation; no FS access) ---------

    @property
    def _replay_log_dir(self) -> Path:
        if self._kind == "mapping":
            return self.workspace_root / "mappings" / "replay-log"
        return self.workspace_root / "distillations" / self.source_id / "replay-log"

    @property
    def _counter_path(self) -> Path:
        return self._replay_log_dir / _COUNTER_FILENAME

    def _entry_path(self, seq: int, timestamp: datetime) -> Path:
        day = timestamp.astimezone(UTC).strftime("%Y-%m-%d")
        return self._replay_log_dir / day / f"{seq:0{_SEQ_WIDTH}d}.yaml"

    # --- Lock-free reads ---------------------------------------------

    def read_seq(self) -> int:
        """Return the current ``.next-seq`` value, or 0 if the counter
        file does not exist.

        Lock-free per plan §5. Concurrent writers see a consistent
        snapshot because ``atomic_write_text`` uses ``os.replace`` —
        readers see either the prior value or the new value, never a
        torn intermediate.
        """
        path = self._counter_path
        if not path.is_file():
            return 0
        return int(path.read_text(encoding="utf-8").strip())

    def list_entries(self) -> Iterable[ReplayLogEntry]:
        """Yield all entries in ``seq``-ascending order.

        Walks day subdirectories in lexicographic order (which matches
        chronological order for ``YYYY-MM-DD`` names) and within each
        day, files sort lexicographically — zero-padded width-12 seq
        names make lexicographic order equal numeric order.

        Skips writer ``.tmp.*`` leftovers (the substrate atomic-write
        pattern from M1.6 may leave them briefly under crash).
        """
        log_dir = self._replay_log_dir
        if not log_dir.is_dir():
            return
        for day_dir in sorted(log_dir.iterdir()):
            if not day_dir.is_dir():
                continue  # Skips the .next-seq counter file.
            for entry_path in sorted(day_dir.iterdir()):
                if not entry_path.is_file():
                    continue
                name = entry_path.name
                if not name.endswith(".yaml"):
                    continue
                if ".tmp." in name:
                    continue
                payload = _safe_load(entry_path.read_text(encoding="utf-8"))
                yield ReplayLogEntry(**payload)

    def get_entry(self, seq: int) -> ReplayLogEntry:
        """Look up an entry by ``seq``.

        Walks day subdirectories to locate the matching file. O(days)
        worst case; acceptable for Phase 1 substrate sizes.

        Raises:
            SubstrateNotFound: if no entry with the given seq exists.
        """
        target_name = f"{seq:0{_SEQ_WIDTH}d}.yaml"
        log_dir = self._replay_log_dir
        if not log_dir.is_dir():
            raise SubstrateNotFound(f"replay log entry seq={seq} not found (no log dir)")
        for day_dir in sorted(log_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            candidate = day_dir / target_name
            if candidate.is_file():
                payload = _safe_load(candidate.read_text(encoding="utf-8"))
                return ReplayLogEntry(**payload)
        raise SubstrateNotFound(f"replay log entry seq={seq} not found")

    # --- Mutating append ---------------------------------------------

    def append(
        self,
        *,
        actor: AgentAttribution,
        activity: str,
        inputs_hash: str,
        outputs_hash: str,
        cache_hit: bool,
        substrate_changes: list[str],
        duration_seconds: float,
        timestamp: datetime | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        cost_estimate_cents: float | None = None,
        lock_timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> ReplayLogEntry:
        """Append one entry to the replay log.

        Assigns ``seq`` from the per-scope counter under the workspace flock.
        Returns the finalized ``ReplayLogEntry`` with ``seq`` populated.

        The ``timestamp`` parameter defaults to the current UTC time
        (tz-aware). A caller supplying a custom timestamp owns its
        correctness (it must be tz-aware per ``ReplayLogEntry`` schema).

        Crash discipline: the entry file is written BEFORE the counter
        is bumped. A crash between those two steps leaves the counter
        at ``N`` and the next writer overwrites the orphan entry. See
        module docstring.

        Args:
            actor: Who/what performed the activity.
            activity: Verb describing the activity (e.g. ``"extract_v1"``).
            inputs_hash: Hash of normalized activity inputs (cache key).
            outputs_hash: Hash of produced outputs.
            cache_hit: ``True`` iff satisfied from prior outputs.
            substrate_changes: Paths written/deleted by the activity.
            duration_seconds: Wall-clock duration.
            timestamp: tz-aware UTC datetime; defaults to ``datetime.now(UTC)``.
            tokens_input: Optional input-token count.
            tokens_output: Optional output-token count.
            cost_estimate_cents: Optional cost telemetry.
            lock_timeout: Seconds to wait for the workspace flock.

        Raises:
            WorkspaceLockTimeout: if the workspace lock cannot be acquired.
            ValueError: if ``lock_timeout`` is negative (propagated from lock layer).
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        with acquire_workspace_lock(self.workspace_root, timeout=lock_timeout):
            # Step 2: read current counter (default 0 if missing).
            current_seq = self.read_seq()

            entry = ReplayLogEntry(
                seq=current_seq,
                timestamp=timestamp,
                actor=actor,
                activity=activity,
                inputs_hash=inputs_hash,
                outputs_hash=outputs_hash,
                cache_hit=cache_hit,
                substrate_changes=substrate_changes,
                duration_seconds=duration_seconds,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                cost_estimate_cents=cost_estimate_cents,
            )
            entry_path = self._entry_path(current_seq, timestamp)

            # Step 3: cross-day orphan recovery. A prior writer may have
            # written its entry at seq N in a different day directory and
            # crashed before bumping the counter (e.g. crash at 23:59 UTC,
            # recovery at 00:01 UTC the next day). ``atomic_write_text``
            # only overwrites the path it is given, so without this scan
            # the orphan would linger in the old day directory while we
            # write to the new one — two files at the same seq, in
            # different days, violating plan §5's "no duplicates"
            # promise. Same-day orphans are handled by ``os.replace``
            # inside ``atomic_write_text`` (the canonical path matches),
            # so we deliberately skip ``entry_path`` itself here.
            target_name = f"{current_seq:0{_SEQ_WIDTH}d}.yaml"
            log_dir = self._replay_log_dir
            if log_dir.is_dir():
                for day_dir in log_dir.iterdir():
                    if not day_dir.is_dir():
                        continue  # Skips the .next-seq counter file.
                    stale = day_dir / target_name
                    if stale != entry_path and stale.is_file():
                        stale.unlink()

            # Step 4: write the entry at seq N atomically.
            payload = entry.model_dump(mode="python")
            atomic_write_text(entry_path, _safe_dump(payload))

            # Step 5: bump the counter to N+1 atomically.
            # Counter file lives at <replay-log>/.next-seq and stores a
            # single decimal integer + trailing newline (POSIX text file
            # hygiene; reader uses .strip()).
            atomic_write_text(self._counter_path, f"{current_seq + 1}\n")

        return entry
