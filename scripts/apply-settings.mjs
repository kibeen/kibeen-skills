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
// 3. CLAUDE.md: keeps settings/CLAUDE.kibeen.md as a marked block in the user's CLAUDE.md
//    (other content untouched, backup first).
//
// Usage: node scripts/apply-settings.mjs [--dry-run | --check] [--hook] [--marketplaces-only]
//   --dry-run            print every step, change nothing
//   --check              print only what differs, change nothing; exit 2 when something differs
//   --hook               print only a Claude Code hook JSON {"systemMessage": ...} (or nothing when in sync)
//   --marketplaces-only  skip enabling plugins (clean-up and marketplace declarations still run)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SELF = path.join(ROOT, "scripts", "apply-settings.mjs");
const fragment = JSON.parse(fs.readFileSync(path.join(ROOT, "settings", "claude-settings.json"), "utf8"));
const catalog = JSON.parse(fs.readFileSync(path.join(ROOT, ".claude-plugin", "marketplace.json"), "utf8"));
const dir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
const file = path.join(dir, "settings.json");
const CHECK = process.argv.includes("--check");
const HOOK = process.argv.includes("--hook");
const DRY = CHECK || process.argv.includes("--dry-run");
const MARKETS_ONLY = process.argv.includes("--marketplaces-only");
const log = HOOK ? () => {} : console.log;

const readSettings = () => (fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {});
let backedUp = false;
function backupOnce() {
  if (backedUp || !fs.existsSync(file)) return;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  backupPath = `${file}.bak-${stamp}`;
  fs.copyFileSync(file, backupPath);
  backedUp = true;
  log(`Backup: ${backupPath}`);
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
  try {
    return JSON.parse(r.out.slice(r.out.indexOf("[")));
  } catch {
    return null;
  }
}

const diffs = []; // human-readable list of what differs from the repo
let failures = 0;
let backupPath = "";

function summary() {
  const count = re => diffs.filter(d => re.test(d)).length;
  return [
    [count(/^install /), "이름 변경 설치"],
    [count(/^(remove marketplace|uninstall)/), "정리"],
    [count(/^marketplace /), "마켓플레이스 선언"],
    [count(/^plugin .*: (enabled|removed)/), "플러그인 켜기·끄기"],
    [count(/^CLAUDE\.md /), "답변 지침"],
  ]
    .filter(([n]) => n)
    .map(([n, label]) => `${label} ${n}건`)
    .join(", ");
}
function hookMessage(text) {
  process.stdout.write(JSON.stringify({ systemMessage: text }) + "\n");
}

// ---- 1. clean-up ---------------------------------------------------------
const retired = fragment.retired || {};
const installed = claudeJson(["plugin", "list", "--json"]);
const known = claudeJson(["plugin", "marketplace", "list", "--json"]);
const plan = [];
if (!installed || !known) {
  log("claude CLI not available: skipping clean-up of retired marketplaces and plugins.");
} else {
  const declared = readSettings().extraKnownMarketplaces || {};
  const knownNames = new Set([...known.map(m => m.name), ...Object.keys(declared)]);
  for (const m of retired.marketplaces || []) {
    if (knownNames.has(m)) plan.push({ what: `remove marketplace ${m}`, args: ["plugin", "marketplace", "remove", m] });
  }
  const goneMarkets = new Set(plan.map(p => p.args[3]));
  const inCatalog = new Set(catalog.plugins.map(p => `${p.name}@${catalog.name}`));
  const retiredPlugins = new Set(retired.plugins || []);
  const installedIds = new Set(installed.map(p => p.id));
  // Renamed plugins: install the new id before the old one is removed below.
  for (const [oldId, newId] of Object.entries(fragment.renamed || {})) {
    if (installedIds.has(oldId) && !installedIds.has(newId))
      plan.push({ what: `install ${newId} (renamed from ${oldId})`, args: ["plugin", "install", newId] });
  }
  for (const { id } of installed) {
    if (goneMarkets.has(id.split("@")[1])) continue; // removed with its marketplace
    if (retiredPlugins.has(id)) plan.push({ what: `uninstall ${id} (retired)`, args: ["plugin", "uninstall", id] });
    else if (id.endsWith(`@${catalog.name}`) && !inCatalog.has(id))
      plan.push({ what: `uninstall ${id} (no longer in ${catalog.name})`, args: ["plugin", "uninstall", id] });
  }
}
for (const step of plan) {
  diffs.push(step.what);
  if (DRY) {
    if (!CHECK) log(`would ${step.what}`);
    continue;
  }
  backupOnce();
  const r = claude(step.args);
  if (!r.ok) failures++;
  log(`${r.ok ? "done" : "FAILED"}: ${step.what}${r.ok ? "" : "\n  " + r.out.trim().split("\n").pop()}`);
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
diffs.push(...report);

// ---- 3. CLAUDE.md instruction block ---------------------------------------
// settings/CLAUDE.kibeen.md is kept as a managed block in the user's CLAUDE.md;
// everything outside the markers is left untouched. No repo file -> block removed.
const memoSrc = path.join(ROOT, "settings", "CLAUDE.kibeen.md");
const memoFile = path.join(dir, "CLAUDE.md");
const BEGIN = "<!-- BEGIN kibeen-skills: managed by apply-settings.mjs, edit settings/CLAUDE.kibeen.md in the repo -->";
const END = "<!-- END kibeen-skills -->";
const memoNow = fs.existsSync(memoFile) ? fs.readFileSync(memoFile, "utf8").replace(/\r\n/g, "\n") : "";
const blockRe = /<!-- BEGIN kibeen-skills[^\n]*-->\n[\s\S]*?<!-- END kibeen-skills -->\n?/;
const wanted = fs.existsSync(memoSrc) ? `${BEGIN}\n${fs.readFileSync(memoSrc, "utf8").replace(/\r\n/g, "\n").trim()}\n${END}\n` : "";
let memoNext = blockRe.test(memoNow)
  ? memoNow.replace(blockRe, wanted)
  : wanted
    ? memoNow + (memoNow && !memoNow.endsWith("\n\n") ? (memoNow.endsWith("\n") ? "\n" : "\n\n") : "") + wanted
    : memoNow;
if (memoNext !== memoNow) {
  const what = !wanted ? "removed" : blockRe.test(memoNow) ? "updated" : "added";
  diffs.push(`CLAUDE.md instructions: ${what}`);
  if (!DRY) {
    if (fs.existsSync(memoFile)) {
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      fs.copyFileSync(memoFile, `${memoFile}.bak-${stamp}`);
    }
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(memoFile, memoNext);
    log(`CLAUDE.md instructions ${what}: ${memoFile}`);
  } else if (!CHECK) log(`would ${what === "removed" ? "remove" : what === "added" ? "add" : "update"} the kibeen-skills block in ${memoFile}`);
}

if (CHECK) {
  if (HOOK) {
    if (diffs.length) hookMessage(`kibeen-skills 설정과 다름 (${summary()}). 확인: node "${SELF}" --dry-run`);
  } else {
    console.log(diffs.length ? `${diffs.length} item(s) differ:\n` + diffs.map(d => "  " + d).join("\n") : "In sync.");
  }
  process.exit(diffs.length ? 2 : 0);
}

log([file, ...(report.length ? report : ["Settings already up to date."]), ...notes].join("\n"));
if (!DRY && report.length) {
  fs.mkdirSync(dir, { recursive: true });
  backupOnce();
  fs.writeFileSync(file, JSON.stringify(next, null, 2) + "\n");
  log("Written. Restart Claude Code; enabled plugins that are not installed yet are fetched on startup.");
}
if (HOOK && !DRY && diffs.length) {
  hookMessage(
    `kibeen-skills 설정을 자동 적용했습니다 (${summary()}${failures ? `, 실패 ${failures}건` : ""}). ` +
      `새로 켠 플러그인은 다음 세션부터 쓸 수 있습니다. 되돌리기: ${backupPath || "백업 없음"}`,
  );
}
