"""M7.2 — orchestrator stub-skip integration test (CV-6 mitigation).

M7.3's CLI-side tests live in ``tests/cli/test_distill_cli.py`` and
verify the orchestrator's stub-skip behaviour at the CLI boundary.
This module sits in ``tests/dispatch/`` because the gate it exercises
is FILESYSTEM-level: when the orchestrator is asked for a stub role,
the dispatch queue must NOT receive an entry for that role, and the
replay-log must record the skip. That is a cross-package invariant
(CLI ↔ dispatch queue ↔ replay log) — closer in spirit to the queue
protocol than to the CLI's parameter parsing.

The three tests below cover:

1. Queue-side discipline: stub roles produce zero queue entries.
2. Replay-log-side discipline: stub roles produce one log entry
   carrying the ``role-skipped:<role>`` token.
3. Fail-closed: a malformed (or unparseable) skill surfaces a clean
   non-zero exit via ``fatal()`` rather than a stack trace.

Per the task brief, CV-6 is a mitigation rather than an invariants-
level gate, so the tests are NOT marked ``@pytest.mark.invariants``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate
from amanuensis.llm.queue import DispatchQueueEntry
from amanuensis.schemas import ReplayLogEntry

runner = CliRunner()

SOURCE_ID = "stub-skip-src"


# --- fixtures -------------------------------------------------------------


@pytest.fixture
def cli_workspace(tmp_path: Path) -> Path:
    """An empty tmpdir with the INV-1 marker.

    Mirrors ``tests/cli/conftest.py``'s fixture of the same name; the
    duplication is intentional — ``tests/dispatch/conftest.py`` already
    exposes ``dispatch_workspace`` for queue-protocol unit tests, and
    keeping the CLI-flavoured fixture local to this file means the
    cross-package integration discipline is self-contained.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: dispatch-stub-skip-test\n",
        encoding="utf-8",
    )
    return tmp_path


def _plant_source_mirror(workspace: Path, source_id: str = SOURCE_ID) -> Path:
    """Create an empty manifest.yaml so the existence check passes.

    The distill command only checks that the manifest path is a file;
    it does not parse the manifest at orchestrate time. An empty file
    is therefore sufficient for the preflight (see
    ``amanuensis/cli/distill.py`` ``manifest_path.is_file()``).
    """
    substrate = Substrate(workspace)
    manifest_path = substrate.manifest_path(source_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("", encoding="utf-8")
    return manifest_path


def _queue_yaml_files(workspace: Path) -> list[Path]:
    """Lex-sorted list of ``.yaml`` files in ``<workspace>/dispatch/queue/``."""
    queue_dir = workspace / "dispatch" / "queue"
    if not queue_dir.is_dir():
        return []
    return sorted(
        p
        for p in queue_dir.iterdir()
        if p.is_file() and p.name.endswith(".yaml") and ".tmp." not in p.name
    )


def _parse_queue_entry(path: Path) -> DispatchQueueEntry:
    """Parse one on-disk queue entry into a typed ``DispatchQueueEntry``.

    We deliberately parse via the schema (not raw YAML) so the test
    fails loudly if the orchestrator writes an entry whose shape
    drifts from the queue contract.
    """
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), f"queue entry at {path} is not a YAML mapping"
    return DispatchQueueEntry.model_validate(raw)


def _read_replay_entries_for_today(
    workspace: Path, source_id: str = SOURCE_ID
) -> list[ReplayLogEntry]:
    """Parse every replay-log entry under today's date directory.

    The replay log is rooted at
    ``<workspace>/distillations/<source_id>/replay-log/<yyyy-mm-dd>/``
    (see ``amanuensis.llm.replay_log.append_replay_entry`` and
    ``amanuensis.fs.replay_log.ReplayLog``). Entries are validated
    through ``ReplayLogEntry.model_validate`` so a schema-drift would
    fail this helper before the assertions could even run.
    """
    today = datetime.now(UTC).date().isoformat()
    day_dir = workspace / "distillations" / source_id / "replay-log" / today
    if not day_dir.is_dir():
        return []
    entries: list[ReplayLogEntry] = []
    for entry_path in sorted(day_dir.glob("*.yaml")):
        raw: Any = yaml.safe_load(entry_path.read_text(encoding="utf-8"))
        entries.append(ReplayLogEntry.model_validate(raw))
    return entries


# --- 1. Queue-side discipline --------------------------------------------


def test_orchestrator_enqueues_extractor_skips_contrarian(
    cli_workspace: Path,
) -> None:
    """``--role-set extractor,auditor,contrarian`` → 2 queue entries, none for contrarian.

    Asserts the FILESYSTEM-level skip discipline: the queue directory
    holds exactly the active-role entries, and each parsed entry's
    ``role`` field is in the active set (extractor / auditor).
    """
    _plant_source_mirror(cli_workspace)

    result = runner.invoke(
        app,
        [
            "distill",
            SOURCE_ID,
            "--role-set",
            "extractor,auditor,contrarian",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code == 0, (
        f"expected exit 0; got {result.exit_code}\noutput: {result.output}"
    )

    queue_files = _queue_yaml_files(cli_workspace)
    assert len(queue_files) == 2, (
        f"expected exactly 2 queue entries (extractor + auditor); "
        f"got {len(queue_files)}: {[p.name for p in queue_files]}"
    )

    entries = [_parse_queue_entry(p) for p in queue_files]
    roles = sorted(entry.role for entry in entries)
    assert roles == ["auditor", "extractor"], (
        f"expected roles [auditor, extractor] in queue; got {roles}"
    )

    # And — explicitly — no entry whose role is the stub role.
    assert not any(entry.role == "contrarian" for entry in entries), (
        f"contrarian is a stub role and must not be enqueued; "
        f"got roles: {[e.role for e in entries]}"
    )


# --- 2. Replay-log-side discipline ---------------------------------------


def test_orchestrator_replay_log_records_stub_skip(cli_workspace: Path) -> None:
    """The skip path appends a replay-log entry whose token names the stub role.

    ``_record_skip`` in ``amanuensis/cli/distill.py`` writes a
    ``ReplayLogEntry`` with ``activity="distill-orchestrate"`` and
    ``substrate_changes`` containing ``"role-skipped:<role>"``. This
    test walks today's date directory and asserts the token is present.
    """
    _plant_source_mirror(cli_workspace)

    result = runner.invoke(
        app,
        [
            "distill",
            SOURCE_ID,
            "--role-set",
            "extractor,auditor,contrarian",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code == 0, (
        f"expected exit 0; got {result.exit_code}\noutput: {result.output}"
    )

    entries = _read_replay_entries_for_today(cli_workspace)
    assert entries, (
        f"expected at least one replay-log entry under today's date dir; "
        f"got none. CLI output:\n{result.output}"
    )

    skip_entries = [
        entry for entry in entries if "role-skipped:contrarian" in entry.substrate_changes
    ]
    assert skip_entries, (
        f"expected a replay-log entry whose substrate_changes contains "
        f"'role-skipped:contrarian'; got entries: "
        f"{[(e.activity, e.substrate_changes) for e in entries]}"
    )

    # The skip entry is recorded by the orchestrator activity.
    assert skip_entries[0].activity == "distill-orchestrate", (
        f"expected skip entry activity 'distill-orchestrate'; got {skip_entries[0].activity!r}"
    )


# --- 3. Fail-closed on malformed frontmatter -----------------------------


def test_malformed_frontmatter_skill_fails_closed(
    cli_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skill that fails to parse must surface a clean non-zero exit.

    The orchestrator must not crash with a stack trace if a role-skill
    file is malformed — it must route through ``fatal()`` so the
    operator gets a clear ``error: distill failed: ...`` line on
    stderr and a non-zero exit. We exercise this by monkeypatching the
    per-role classifier (``_classify_role``) — wrapped in the
    distill command's ``try/except`` (see ``cli/distill.py`` around
    the role loop) — so it raises ``ValueError`` as if the underlying
    ``split_frontmatter`` had rejected the file.

    Patching ``_classify_role`` (rather than ``split_frontmatter``
    directly) is the least-invasive seam: it leaves the orchestrator's
    own skill load (``_load_skill("distill.md")``, executed before the
    role loop) intact, so this test isolates the fail-closed contract
    to the role-classification step where a real malformed role skill
    would surface.
    """
    _plant_source_mirror(cli_workspace)

    from amanuensis.cli import distill as distill_module

    def _raise_malformed(role: str) -> tuple[str, str]:
        raise ValueError(
            f"simulated malformed frontmatter for role {role!r}: "
            "skill text does not start with '---' frontmatter fence"
        )

    monkeypatch.setattr(distill_module, "_classify_role", _raise_malformed)

    result = runner.invoke(
        app,
        [
            "distill",
            SOURCE_ID,
            "--role-set",
            "extractor",
            "--workspace",
            str(cli_workspace),
        ],
    )

    assert result.exit_code != 0, (
        f"expected non-zero exit when role skill is malformed; got 0\noutput: {result.output}"
    )
    # The error must be surfaced via ``fatal()`` (which prefixes
    # ``error: distill failed:``) — NOT a raw traceback.
    assert "distill failed" in result.output, (
        f"expected 'distill failed' in CLI output; got:\n{result.output}"
    )
    # Sanity: the queue must NOT have received an entry for the
    # role whose classification raised — fail-closed means no partial
    # state written.
    assert _queue_yaml_files(cli_workspace) == [], (
        f"expected no queue entries when classification fails; got "
        f"{[p.name for p in _queue_yaml_files(cli_workspace)]}"
    )
