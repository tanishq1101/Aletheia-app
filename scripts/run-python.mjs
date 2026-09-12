#!/usr/bin/env node
/**
 * Run one of the backend's Python scripts through the project virtualenv.
 *
 * The npm scripts used to name the interpreter directly as
 * `backend/.venv/bin/python`, which does not exist on Windows — the venv puts
 * it in `Scripts/python.exe`. That would be a small annoyance except for how
 * it failed: cmd.exe printed "'backend' is not recognized" and npm still
 * exited 0, so `npm run db:verify` — the guard that asserts the indexes and
 * CHECK constraints Prisma cannot express are still present — reported success
 * on Windows without running at all. A safety net that passes vacuously is
 * worse than not having one.
 *
 * So: resolve the interpreter for this platform, fail loudly if it is missing,
 * and propagate the real exit code.
 *
 *   node scripts/run-python.mjs backend/scripts/verify_schema.py [args...]
 */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const candidates =
  process.platform === "win32"
    ? [path.join(root, "backend", ".venv", "Scripts", "python.exe")]
    : [path.join(root, "backend", ".venv", "bin", "python")];

const interpreter = candidates.find(existsSync);

if (!interpreter) {
  console.error(
    `No project virtualenv found. Looked for:\n  ${candidates.join("\n  ")}\n\n` +
      "Create it with:\n" +
      "  python -m venv backend/.venv\n" +
      (process.platform === "win32"
        ? "  backend/.venv/Scripts/python -m pip install -r backend/apps/api/requirements.txt"
        : "  backend/.venv/bin/python -m pip install -r backend/apps/api/requirements.txt"),
  );
  process.exit(1);
}

const [script, ...args] = process.argv.slice(2);
if (!script) {
  console.error("Usage: node scripts/run-python.mjs <script.py> [args...]");
  process.exit(1);
}

const result = spawnSync(interpreter, [path.join(root, script), ...args], {
  stdio: "inherit",
  cwd: root,
});

if (result.error) {
  console.error(`Could not run ${script}: ${result.error.message}`);
  process.exit(1);
}

// A script killed by a signal has no exit code; treat that as a failure
// rather than letting `undefined` become a silent 0.
process.exit(result.status ?? 1);
