#!/usr/bin/env node
// Bring this machine's Claude Code user settings in line with settings/claude-settings.json
// (~/.claude/settings.json, or $CLAUDE_CONFIG_DIR/settings.json).
//
// 1. Clean up (uses the `claude` CLI):
//    - removes the marketplaces listed in `retired.marketplaces` (this also uninstalls their plugins),
//    - uninstalls the plugins listed in `retired.plugins`,
//    - uninstalls kibeen-skills plugins that are no longer in .claude-plugin/marketplace.json.
// 2. Merge:
//    - extraKnownMarketplaces: entries from the repo file replace same-named entries.
//    - enabledPlugins: adds the repo's plugins; a plugin this machine set to false stays false.
//    - Every other key in settings.json is left as is. A timestamped backup is written first.
//
// Usage: node scripts/apply-settings.mjs [--dry-run] [--marketplaces-only]
//   --marketplaces-only  skip enabling plugins (clean-up and marketplace declarations still run)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fragment = JSON.parse(fs.readFileSync(path.join(ROOT, "settings", "claude-settings.json"), "utf8"));
const catalog = JSON.parse(fs.readFileSync(path.join(ROOT, ".claude-plugin", "marketplace.json"), "utf8"));
const dir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
const file = path.join(dir, "settings.json");
const DRY = process.argv.includes("--dry-run");
const MARKETS_ONLY = process.argv.includes("--marketplaces-only");

const readSettings = () => (fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {});
let backedUp = false;
function backupOnce() {
  if (backedUp || !fs.existsSync(file)) return;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  fs.copyFileSync(file, `${file}.bak-${stamp}`);
  backedUp = true;
  console.log(`Backup: ${file}.bak-${stamp}`);
}

function claude(args) {
  let r = spawnSync("claude", args, { encoding: "utf8" });
  if (r.error?.code === "ENOENT" && process.platform === "win32") {
    // npm installs claude as claude.cmd, which only runs through the shell.
    const cmd = ["claude", ...args].map(a => (/^[\w@./:-]+$/.test(a) ? a : `"${a}"`)).join(" ");
    r = spawnSync(cmd, { encoding: "utf8", shell: true });
  }
  return { ok: r.status === 0, out: (r.stdout || "") + (r.stderr || "") };
}
function claudeJson(args) {
  const r = claude(args);
  if (!r.ok) return null;
  const start = r.out.indexOf("[");
  try {
    return JSON.parse(r.out.slice(start));
  } catch {
    return null;
  }
}

// ---- 1. clean-up ---------------------------------------------------------
const retired = fragment.retired || {};
const installed = claudeJson(["plugin", "list", "--json"]);
const known = claudeJson(["plugin", "marketplace", "list", "--json"]);
const plan = [];
if (!installed || !known) {
  console.log("claude CLI not available: skipping clean-up of retired marketplaces and plugins.");
} else {
  const declared = readSettings().extraKnownMarketplaces || {};
  const knownNames = new Set([...known.map(m => m.name), ...Object.keys(declared)]);
  for (const m of retired.marketplaces || []) {
    if (knownNames.has(m)) plan.push({ what: `remove marketplace ${m}`, args: ["plugin", "marketplace", "remove", m] });
  }
  const goneMarkets = new Set(plan.map(p => p.args[3]));
  const inCatalog = new Set(catalog.plugins.map(p => `${p.name}@${catalog.name}`));
  const retiredPlugins = new Set(retired.plugins || []);
  for (const { id } of installed) {
    if (goneMarkets.has(id.split("@")[1])) continue; // removed with its marketplace
    if (retiredPlugins.has(id)) plan.push({ what: `uninstall ${id} (retired)`, args: ["plugin", "uninstall", id] });
    else if (id.endsWith(`@${catalog.name}`) && !inCatalog.has(id))
      plan.push({ what: `uninstall ${id} (no longer in ${catalog.name})`, args: ["plugin", "uninstall", id] });
  }
}
for (const step of plan) {
  if (DRY) {
    console.log(`would ${step.what}`);
    continue;
  }
  backupOnce();
  const r = claude(step.args);
  console.log(`${r.ok ? "done" : "FAILED"}: ${step.what}${r.ok ? "" : "\n  " + r.out.trim().split("\n").pop()}`);
}

// ---- 2. merge ------------------------------------------------------------
const current = readSettings(); // re-read: the CLI above edits settings.json
const next = structuredClone(current);
const report = [];
const notes = [];

next.extraKnownMarketplaces = { ...(current.extraKnownMarketplaces || {}) };
for (const [name, entry] of Object.entries(fragment.extraKnownMarketplaces || {})) {
  if (JSON.stringify(current.extraKnownMarketplaces?.[name]) === JSON.stringify(entry)) continue;
  next.extraKnownMarketplaces[name] = entry;
  report.push(`marketplace ${name}: ${current.extraKnownMarketplaces?.[name] ? "updated" : "added"}`);
}
for (const m of retired.marketplaces || []) {
  if (!next.extraKnownMarketplaces[m]) continue;
  delete next.extraKnownMarketplaces[m];
  report.push(`marketplace ${m}: declaration removed`);
}

next.enabledPlugins = { ...(current.enabledPlugins || {}) };
for (const id of retired.plugins || []) {
  if (!(id in next.enabledPlugins)) continue;
  delete next.enabledPlugins[id];
  report.push(`plugin ${id}: removed from enabledPlugins`);
}
if (!MARKETS_ONLY) {
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

console.log([file, ...(report.length ? report : ["Settings already up to date."]), ...notes].join("\n"));
if (DRY || !report.length) process.exit(0);

fs.mkdirSync(dir, { recursive: true });
backupOnce();
fs.writeFileSync(file, JSON.stringify(next, null, 2) + "\n");
console.log("Written. Restart Claude Code; enabled plugins that are not installed yet are fetched on startup.");
