"""Echo-role fixture test (M6.4, CV-7 mitigation).

A synthetic shell-script "echo role" exercises the dispatch protocol
end-to-end without requiring any real harness CLI installation. The
fixture is written into the test's tmpdir each run and pointed at via
the driver's :data:`TEST_HARNESS_OVERRIDES` injection seam.

Three contracts:

1. The driver picks up the echo script exactly like a real harness;
   stdout YAML lands in ``dispatch/outputs/``.
2. A second drive with identical inputs is a cache hit — no subprocess
   invocation.
3. A malformed-output echo script routes the entry to
   ``dispatch/failures/`` with ``reason="output-parse-error"``.

Implementation note: every script + aux file (counter, stdin marker)
lives OUTSIDE the dispatch workspace tree. The driver's write-
isolation check (CV-5) would otherwise flag those auxiliary writes
as violations, since they are not inside the role's assigned output
directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.cli.dispatch import TEST_HARNESS_OVERRIDES
from amanuensis.dispatch.queue import enqueue, list_queue

from .conftest import make_entry

runner = CliRunner()


def _write_echo_script(aux_dir: Path, *, stdout_content: str, exit_code: int = 0) -> Path:
    """Plant an executable shell script that echoes ``stdout_content``."""
    script_path = aux_dir / "echo_role.sh"
    body = "#!/bin/sh\n"
    body += "cat <<'__ECHO_ROLE_EOF__'\n"
    body += stdout_content
    if not stdout_content.endswith("\n"):
        body += "\n"
    body += "__ECHO_ROLE_EOF__\n"
    body += f"exit {exit_code}\n"
    script_path.write_text(body, encoding="utf-8")
    script_path.chmod(0o700)
    return script_path


def _drive_once(workspace: Path) -> int:
    """Invoke ``amanuensis dispatch --once`` against ``workspace``."""
    result = runner.invoke(
        app,
        ["dispatch", "--once", "--workspace", str(workspace)],
    )
    assert result.exit_code == 0, (
        f"dispatch --once failed (exit={result.exit_code})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result.exit_code


def test_echo_role_success_routes_to_outputs(
    dispatch_workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Driver invokes the echo script; YAML stdout lands under outputs/."""
    aux = tmp_path_factory.mktemp("aux-echo-ok")
    script = _write_echo_script(
        aux,
        stdout_content='{"atoms": [{"id": "a-1", "predicate": "p"}], "findings": []}',
    )
    TEST_HARNESS_OVERRIDES["claude"] = script
    try:
        entry = make_entry(role="extractor", inputs_hash="e" * 64)
        enqueue(dispatch_workspace, entry)

        _drive_once(dispatch_workspace)

        out_path = (
            dispatch_workspace
            / "dispatch"
            / "outputs"
            / f"extractor-{entry.inputs_hash}"
            / "output.yaml"
        )
        assert out_path.is_file(), "expected dispatch output to be written"

        assert list_queue(dispatch_workspace) == []
    finally:
        TEST_HARNESS_OVERRIDES.pop("claude", None)


def test_echo_role_second_drive_is_cache_hit(
    dispatch_workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Second dispatch with identical inputs ⇒ no subprocess invocation."""
    aux = tmp_path_factory.mktemp("aux-echo-cache")
    counter_file = aux / "invocation_count.txt"
    script_path = aux / "counting_echo.sh"
    body = (
        "#!/bin/sh\n"
        f'printf "x" >> "{counter_file}"\n'
        "cat <<'__EOF__'\n"
        '{"atoms": [], "findings": []}\n'
        "__EOF__\n"
        "exit 0\n"
    )
    script_path.write_text(body, encoding="utf-8")
    script_path.chmod(0o700)

    TEST_HARNESS_OVERRIDES["claude"] = script_path
    try:
        entry = make_entry(role="extractor", inputs_hash="c" * 64)

        # First drive: cache miss, script invoked.
        enqueue(dispatch_workspace, entry)
        _drive_once(dispatch_workspace)
        first_count = counter_file.read_text(encoding="utf-8") if counter_file.is_file() else ""
        assert len(first_count) == 1, (
            f"expected 1 invocation after first drive, got {len(first_count)}"
        )

        # Re-enqueue the SAME entry (cache should hit on second drive).
        enqueue(dispatch_workspace, entry)
        _drive_once(dispatch_workspace)
        second_count = counter_file.read_text(encoding="utf-8")
        assert len(second_count) == 1, (
            f"expected NO new invocation on cache hit, got {len(second_count) - 1} extra calls"
        )

        out_path = (
            dispatch_workspace
            / "dispatch"
            / "outputs"
            / f"extractor-{entry.inputs_hash}"
            / "output.yaml"
        )
        assert out_path.is_file()
    finally:
        TEST_HARNESS_OVERRIDES.pop("claude", None)


def test_echo_role_malformed_output_routes_to_failures(
    dispatch_workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Garbage stdout ⇒ failure with reason ``output-parse-error``."""
    aux = tmp_path_factory.mktemp("aux-echo-malformed")
    script = _write_echo_script(
        aux,
        stdout_content="this is not yaml: : : :::",
    )
    TEST_HARNESS_OVERRIDES["claude"] = script
    try:
        entry = make_entry(role="extractor", inputs_hash="b" * 64)
        enqueue(dispatch_workspace, entry)

        _drive_once(dispatch_workspace)

        assert list_queue(dispatch_workspace) == []
        failures_dir = dispatch_workspace / "dispatch" / "failures"
        failure_files = list(failures_dir.iterdir())
        assert failure_files, "expected at least one failure record"

        sidecars = [p for p in failure_files if p.name.endswith(".failure.yaml")]
        assert sidecars, "expected a .failure.yaml sidecar"

        sidecar_payload: Any = yaml.safe_load(sidecars[0].read_text(encoding="utf-8"))
        assert sidecar_payload["reason"] == "output-parse-error"
    finally:
        TEST_HARNESS_OVERRIDES.pop("claude", None)


def test_echo_role_uses_devnull_stdin(
    dispatch_workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Driver passes ``stdin=DEVNULL``; a script that reads stdin sees EOF.

    Catches the regression where a harness invocation forgot the
    ``< /dev/null`` discipline and blocked forever waiting for input.
    """
    aux = tmp_path_factory.mktemp("aux-echo-stdin")
    stdin_marker = aux / "stdin_bytes.txt"
    script_path = aux / "stdin_reader.sh"
    body = (
        "#!/bin/sh\n"
        f'cat > "{stdin_marker}"\n'
        "cat <<'__EOF__'\n"
        '{"atoms": [], "findings": []}\n'
        "__EOF__\n"
        "exit 0\n"
    )
    script_path.write_text(body, encoding="utf-8")
    script_path.chmod(0o700)

    TEST_HARNESS_OVERRIDES["claude"] = script_path
    try:
        entry = make_entry(role="extractor", inputs_hash="d" * 64)
        enqueue(dispatch_workspace, entry)
        _drive_once(dispatch_workspace)

        # stdin marker should be present but empty (DEVNULL ⇒ EOF immediately).
        assert stdin_marker.is_file()
        assert stdin_marker.read_bytes() == b""
    finally:
        TEST_HARNESS_OVERRIDES.pop("claude", None)
