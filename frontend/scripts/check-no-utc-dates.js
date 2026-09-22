#!/usr/bin/env node
// =============================================================================
// === frontend/scripts/check-no-utc-dates.js ===
// =============================================================================
// 21 Sep 2026 — the frontend twin of backend/apps/core/test_no_raw_utc_dates.py.
//
// Fails loudly if `new Date().toISOString().slice(0, 10)` (or the equivalent
// `.substring(0, 10)`) reappears anywhere in frontend/app, frontend/components
// or frontend/lib. That pattern reads the UTC calendar day, which is still
// YESTERDAY in Jakarta (UTC+7) between 00:00 and 07:00 WIB — the exact bug
// swept out of 14 pages on 20-21 Sep 2026 (Roadmap Open Decision #35).
// Every one of those pages now uses todayISO() from lib/format.ts instead.
//
// Plain regex over the raw source, not an AST — this project has no ESLint
// config yet, and a look-behind regex is enough to tell the two lines this
// file itself needs to mention apart from a real, live occurrence (see below).
//
// Run directly:   node frontend/scripts/check-no-utc-dates.js
// Wired into `npm run build` via the "prebuild" script in package.json, so it
// always runs before a production build, in dev and on the server, with no
// extra step to remember.
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");                       // frontend/
const SCAN_DIRS = ["app", "components", "lib"].map((d) => path.join(ROOT, d));
const EXTENSIONS = new Set([".ts", ".tsx"]);
const SELF = __filename;                                       // never flag this file's own comments

// Matches new Date().toISOString().slice(0, 10) / .substring(0, 10), tolerant
// of extra whitespace and either quote style is irrelevant (no quotes here).
const PATTERN = /new\s+Date\s*\(\s*\)\s*\.\s*toISOString\s*\(\s*\)\s*\.\s*(?:slice|substring)\s*\(\s*0\s*,\s*10\s*\)/;

function walk(dir, out) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (err) {
    if (err.code === "ENOENT") return out;                     // a scanned dir may not exist yet
    throw err;
  }
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, out);
    } else if (EXTENSIONS.has(path.extname(entry.name)) && full !== SELF) {
      out.push(full);
    }
  }
  return out;
}

function findOffenders() {
  const files = SCAN_DIRS.flatMap((d) => walk(d, []));
  const offenders = [];
  for (const file of files) {
    const text = fs.readFileSync(file, "utf8");
    const lines = text.split("\n");
    lines.forEach((line, i) => {
      const stripped = line.trim();
      // Skip comments/docstrings that merely DESCRIBE the pattern (this file's
      // own header, and the explanatory comments left in the 14 swept files) —
      // mirrors the backend test's AST-based exclusion of non-code occurrences.
      if (stripped.startsWith("//") || stripped.startsWith("*") || stripped.startsWith("/*")) return;
      if (PATTERN.test(line)) {
        offenders.push(`${path.relative(ROOT, file)}:${i + 1}`);
      }
    });
  }
  return offenders;
}

function main() {
  const offenders = findOffenders();
  if (offenders.length === 0) {
    console.log("check-no-utc-dates: OK — no raw UTC-day date defaults found.");
    return 0;
  }
  console.error("check-no-utc-dates: FAILED\n");
  console.error("Found new Date().toISOString().slice(0, 10) — this reads the UTC day, which");
  console.error("is still YESTERDAY in Jakarta between 00:00 and 07:00 WIB. Use todayISO()");
  console.error('from "@/lib/format" instead:\n');
  offenders.forEach((o) => console.error("  " + o));
  console.error("");
  return 1;
}

process.exit(main());
