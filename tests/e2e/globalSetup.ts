// globalSetup — generates the fixture workspace consumed by the E2E suite.
//
// Strategy: shell out to a small Python helper (`_fixture_builder.py`) that
// uses the project's own Substrate + schemas API. This keeps the fixture
// authored against the real on-disk format (no risk of drift) at the cost
// of one Python subprocess per `playwright test` invocation. The helper is
// idempotent — it skips rebuild if the marker + an empty `.built` sentinel
// already exist.
//
// Two distillations are planted:
//   * `phase1-smoke`     — 1 atom, 1 relation, 1 paragraph (smoke + state-persistence)
//   * `phase1-stress`    — 250 atoms, 750 relations, planted in batch
// 250/750 is the documented downgrade from the 1000/3000 target (CLAUDE.md
// permits the downgrade; rationale: the soft cap is 750 atoms / 2000 edges,
// so 250/750 is enough to exercise both the under-cap render path and a
// meaningful subset of the over-cap behavior without making globalSetup
// take more than a minute).

import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

const WORKSPACE = path.resolve(__dirname, "fixtures", "workspace");
const BUILDER = path.resolve(__dirname, "_fixture_builder.py");
const SENTINEL = path.join(WORKSPACE, ".built");
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");

// macOS self-heal: the project's `.venv` periodically picks up the
// `hidden` BSD file flag on its `*.pth` files (pre-push hook + macOS
// fs quirk; see HISTORY.md). When Python's `site` module skips hidden
// `.pth` files, the editable install drops off `sys.path` and uvicorn
// can't import `amanuensis`. We sweep `nohidden` here before any
// subprocess uses the venv. Safe no-op on Linux.
function unhideVenvPthFiles(): void {
  if (process.platform !== "darwin") {
    return;
  }
  const venvDir = path.join(PROJECT_ROOT, ".venv");
  if (!fs.existsSync(venvDir)) {
    return;
  }
  try {
    execFileSync(
      "find",
      [venvDir, "-name", "*.pth", "-exec", "chflags", "nohidden", "{}", "+"],
      { stdio: "pipe" },
    );
  } catch {
    // The flag may already be clear; don't fail globalSetup over a
    // self-heal best-effort.
  }
}

export default async function globalSetup(): Promise<void> {
  unhideVenvPthFiles();

  // Note on ordering: Playwright starts `webServer` BEFORE running
  // globalSetup, so the inline `_fixture_builder.py` invocation in
  // playwright.config.ts is what guarantees the fixture exists before
  // the first test request hits the server. This globalSetup is a
  // safety net for two cases:
  //   * `reuseExistingServer: true` and the server was started with a
  //     stale (or absent) fixture.
  //   * A future change moves the fixture builder out of the webServer
  //     command.
  if (fs.existsSync(SENTINEL) && fs.existsSync(path.join(WORKSPACE, "amanuensis.yaml"))) {
    // eslint-disable-next-line no-console
    console.log(`[e2e] fixture workspace present at ${WORKSPACE}`);
    return;
  }

  if (fs.existsSync(WORKSPACE)) {
    fs.rmSync(WORKSPACE, { recursive: true, force: true });
  }
  fs.mkdirSync(WORKSPACE, { recursive: true });

  // eslint-disable-next-line no-console
  console.log(`[e2e] building fixture workspace at ${WORKSPACE} ...`);
  execFileSync("uv", ["run", "--no-sync", "python", BUILDER, WORKSPACE], {
    cwd: PROJECT_ROOT,
    stdio: "inherit",
  });
  fs.writeFileSync(SENTINEL, "built\n", { encoding: "utf-8" });
  // eslint-disable-next-line no-console
  console.log(`[e2e] fixture workspace ready`);
}
