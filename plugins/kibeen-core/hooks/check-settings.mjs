#!/usr/bin/env node
// SessionStart hook: at most once a day, compare this machine with the kibeen-skills
// settings and show the user a one-line notice when they differ. It never changes
// anything and never adds text to the model's context (it only emits systemMessage).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const INTERVAL_MS = 24 * 60 * 60 * 1000;
const configDir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
const dataDir = process.env.CLAUDE_PLUGIN_DATA || path.join(configDir, "plugins", "data", "kibeen-core");
const stampFile = path.join(dataDir, "last-check.json");

try {
  const last = fs.existsSync(stampFile) ? JSON.parse(fs.readFileSync(stampFile, "utf8")).at || 0 : 0;
  if (Date.now() - last < INTERVAL_MS) process.exit(0);

  // The kibeen-skills marketplace checkout (kept current by auto-update) holds the script and settings.
  let script = path.join(configDir, "plugins", "marketplaces", "kibeen-skills", "scripts", "apply-settings.mjs");
  if (!fs.existsSync(script)) {
    // Fall back to asking the CLI where the marketplace lives (e.g. a local-directory marketplace).
    const ls = spawnSync("claude", ["plugin", "marketplace", "list", "--json"], { encoding: "utf8", timeout: 10000 });
    const out = ls.stdout || "";
    const loc = JSON.parse(out.slice(out.indexOf("[")) || "[]").find(m => m.name === "kibeen-skills")?.installLocation;
    script = loc ? path.join(loc, "scripts", "apply-settings.mjs") : "";
    if (!script || !fs.existsSync(script)) process.exit(0);
  }

  const r = spawnSync(process.execPath, [script, "--check", "--hook"], { encoding: "utf8", timeout: 15000 });
  fs.mkdirSync(dataDir, { recursive: true });
  fs.writeFileSync(stampFile, JSON.stringify({ at: Date.now(), status: r.status }) + "\n");
  if (r.stdout && r.stdout.trim().startsWith("{")) process.stdout.write(r.stdout);
} catch {
  // A failed check must never get in the way of starting a session.
}
process.exit(0);
