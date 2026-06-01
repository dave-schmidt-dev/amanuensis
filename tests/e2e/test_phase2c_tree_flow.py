"""Phase 2c M13 T13.2 — probandum-tree E2E spec marker.

The actual E2E coverage for the Phase 2c probandum-tree flow lives in
the sibling ``test_phase2c_tree_flow.spec.ts`` file and is driven by
``test_playwright_runs.py``'s npx-playwright shell-out (the same path
Phase 2b's ``test_phase2b_overlay_flow.spec.ts`` rides). This module
exists solely so the pytest-side import graph documents the existence
of the .spec.ts file and a developer scanning ``tests/e2e/`` sees a
parallel ``.py`` shape next to every named .spec.ts.

The single sanity check here asserts:

1. The .spec.ts file exists on disk next to this module (catches
   accidental rename / deletion that would otherwise vanish silently
   from the npx run because Playwright's discovery is glob-based).
2. The fixture builder's ``plant_probandum_tree`` helper is importable
   and produces the three expected probanda ids (smoke-test for the
   T13.2 fixture extension).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_THIS_DIR: Path = Path(__file__).resolve().parent
_SPEC_PATH: Path = _THIS_DIR / "test_phase2c_tree_flow.spec.ts"
_FIXTURE_BUILDER: Path = _THIS_DIR / "_fixture_builder.py"


def _load_fixture_builder() -> ModuleType:
    """Load the sibling ``_fixture_builder.py`` via importlib."""
    spec = importlib.util.spec_from_file_location("_fixture_builder", _FIXTURE_BUILDER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_phase2c_tree_flow_spec_file_present() -> None:
    """The Playwright .spec.ts file lives next to this module."""
    assert _SPEC_PATH.is_file(), (
        f"expected {_SPEC_PATH} on disk for the Phase 2c tree-flow E2E spec"
    )
    body = _SPEC_PATH.read_text(encoding="utf-8")
    # Cheap smoke: the spec must reference the three URL surfaces it
    # exercises so a future refactor that drops a surface gets caught.
    for fragment in ("/probanda", "/tree", "/tree.json"):
        assert fragment in body, f"spec is missing the {fragment!r} URL fragment"


def test_plant_probandum_tree_helper_smoke(tmp_path: Path) -> None:
    """The fixture-builder helper plants 1 ultimate + 1 penultimate + 1 interim."""
    from amanuensis.fs import Substrate

    builder = _load_fixture_builder()
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: phase2c-tree-flow-smoke\n",
        encoding="utf-8",
    )
    substrate = Substrate(tmp_path)
    ids = builder.plant_probandum_tree(substrate)
    assert set(ids.keys()) == {"ultimate", "penultimate", "interim"}
    for key, prob_id in ids.items():
        assert prob_id.startswith("p-"), f"{key} id {prob_id!r} is not a probandum id"
    # And the three records actually land on disk under mappings/probanda/.
    probanda = list(substrate.list_probanda())
    assert len(probanda) == 3, f"expected 3 probanda on disk; got {len(probanda)}"
