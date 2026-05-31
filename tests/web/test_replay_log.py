"""M8.7 replay-log route tests.

Covers:

- empty workspace renders 200 + empty-state copy.
- a planted replay entry surfaces on the page (activity rendered).
- ``?activity=foo`` substring filter narrows to matching entries only.

Per the M8.7 contract, ``src/amanuensis/web/app.py`` is wired by the
orchestrator only after the wave-3 sibling subagents land. Until then,
this test module mounts the M8.7 router manually onto a fresh app so
the route is reachable without touching ``app.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.llm import append_replay_entry
from amanuensis.schemas import AgentAttribution, ReplayLogEntry
from amanuensis.web.app import create_app
from amanuensis.web.routes import status as status_routes

from .conftest import SOURCE_ID


def _build_client(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Spin up a TestClient with the M8.7 router mounted.

    Mirrors the "manually mount router" workaround the M8.7 task spec
    calls out: ``app.py`` will eventually include this router, but we
    must not modify it here, so each test mounts it on a fresh app.
    """
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    app = create_app()
    app.include_router(status_routes.router)
    return TestClient(app)


def _plant_entry(
    workspace: Path,
    *,
    activity: str,
    actor_identifier: str = "test-model",
) -> ReplayLogEntry:
    """Append one ReplayLogEntry via the M5.2 facade."""
    entry = ReplayLogEntry(
        seq=0,  # overwritten by the appender
        timestamp=datetime.now(UTC),
        actor=AgentAttribution(kind="llm", identifier=actor_identifier, role="extractor"),
        activity=activity,
        inputs_hash="a" * 64,
        outputs_hash="b" * 64,
        cache_hit=False,
        substrate_changes=[f"distillations/{SOURCE_ID}/atoms/a-{'0' * 16}.md"],
        duration_seconds=0.25,
    )
    append_replay_entry(workspace, entry, source_id=SOURCE_ID)
    return entry


def test_replay_log_empty_workspace_returns_empty_table(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh workspace renders 200 + the empty-state copy."""
    client = _build_client(web_workspace, monkeypatch)
    response = client.get("/replay-log")
    assert response.status_code == 200
    body = response.text
    # Empty-state panel from replay_log.html.
    assert "no replay-log entries" in body.lower()
    # Workspace path always surfaces so the supervisor can confirm scope.
    assert str(web_workspace) in body


def test_replay_log_lists_planted_entry(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A planted entry's activity name appears on the page."""
    entry = _plant_entry(web_workspace, activity="extract-propose-v1")
    client = _build_client(web_workspace, monkeypatch)
    response = client.get("/replay-log")
    assert response.status_code == 200
    body = response.text
    assert entry.activity in body
    # The actor identifier is rendered too — proves the row, not just a
    # stray substring match somewhere else in the template.
    assert entry.actor.identifier in body
    # source_id surfaces in the row.
    assert SOURCE_ID in body


def test_replay_log_filters_by_activity(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?activity=foo`` returns only the foo entry."""
    _plant_entry(web_workspace, activity="foo-activity")
    _plant_entry(web_workspace, activity="bar-activity")
    client = _build_client(web_workspace, monkeypatch)

    response = client.get("/replay-log?activity=foo")
    assert response.status_code == 200
    body = response.text
    assert "foo-activity" in body
    assert "bar-activity" not in body
