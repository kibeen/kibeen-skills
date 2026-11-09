#!/usr/bin/env node
// Merge settings/claude-settings.json into this machine's Claude Code user settings
// (~/.claude/settings.json, or $CLAUDE_CONFIG_DIR/settings.json).
//
// - extraKnownMarketplaces: entries from the repo file replace same-named entries.
// - enabledPlugins: adds the repo's plugins; a plugin this machine set to false stays false.
// - Every other key in settings.json is left as is. A timestamped backup is written first.
//
// Usage: node scripts/apply-settings.mjs [--dry-run] [--marketplaces-only]
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fragment = JSON.parse(fs.readFileSync(path.join(ROOT, "settings", "claude-settings.json"), "utf8"));
const dir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
const file = path.join(dir, "settings.json");
const DRY = process.argv.includes("--dry-run");
const MARKETS_ONLY = process.argv.includes("--marketplaces-only");

const current = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
const next = structuredClone(current);
const report = [];
const notes = [];

next.extraKnownMarketplaces = { ...(current.extraKnownMarketplaces || {}) };
for (const [name, entry] of Object.entries(fragment.extraKnownMarketplaces || {})) {
  if (JSON.stringify(current.extraKnownMarketplaces?.[name]) === JSON.stringify(entry)) continue;
  next.extraKnownMarketplaces[name] = entry;
  report.push(`marketplace ${name}: ${current.extraKnownMarketplaces?.[name] ? "updated" : "added"}`);
}

if (!MARKETS_ONLY) {
  next.enabledPlugins = { ...(current.enabledPlugins || {}) };
  for (const [id, on] of Object.entries(fragment.enabledPlugins || {})) {
    if (current.enabledPlugins?.[id] === false) {
      notes.push(`plugin ${id}: kept disabled on this machine`);
      continue;
    }
    if (current.enabledPlugins?.[id] === on) continue;
    next.enabledPlugins[id] = on;
    report.push(`plugin ${id}: enabled`);
  }
}

console.log([file, ...(report.length ? report : ["Already up to date."]), ...notes].join("\n"));
if (DRY || !report.length) process.exit(0);

fs.mkdirSync(dir, { recursive: true });
if (fs.existsSync(file)) {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  fs.copyFileSync(file, `${file}.bak-${stamp}`);
}
fs.writeFileSync(file, JSON.stringify(next, null, 2) + "\n");
console.log("Written. Restart Claude Code; enabled plugins that are not installed yet are fetched on startup.");
