#!/usr/bin/env node
// Bump the pinned upstream commits and npm versions in .claude-plugin/marketplace.json
// (and plugins/*/.mcp.json) to the latest upstream release.
//
// - github / url sources: sha -> latest commit on `ref` (default branch when unset).
// - git-subdir sources:   sha -> latest commit that touched `path`, so a busy monorepo
//   only moves a plugin when its own folder changed.
// - npm args pinned as `pkg@x.y.z` in mcpServers: -> latest stable version.
//
// Env: GITHUB_TOKEN (recommended, raises the API rate limit),
//      MIN_AGE_DAYS (default 0; only adopt commits/versions at least this old).
// Usage: node scripts/sync-upstream.mjs [--dry-run]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MARKETPLACE = path.join(ROOT, ".claude-plugin", "marketplace.json");
const TOKEN = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
const MIN_AGE_DAYS = Number(process.env.MIN_AGE_DAYS || 0);
const DRY = process.argv.includes("--dry-run");
const CUTOFF = MIN_AGE_DAYS > 0 ? new Date(Date.now() - MIN_AGE_DAYS * 864e5) : null;

const changes = [];
const failures = [];

async function getJson(url, headers = {}) {
  const res = await fetch(url, { headers: { "User-Agent": "kibeen-skills-sync", ...headers } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} ${url}`);
  return res.json();
}
const gh = p =>
  getJson(`https://api.github.com${p}`, {
    Accept: "application/vnd.github+json",
    ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
  });

function repoOf(src) {
  if (src.source === "github") return src.repo;
  const m = /github\.com[/:]([^/]+\/[^/]+?)(?:\.git)?\/?$/.exec(src.url || "");
  return m ? m[1] : null;
}

const latestMemo = new Map();
async function latestCommit(repo, ref, subpath) {
  const key = `${repo}|${ref || ""}|${subpath || ""}`;
  if (!latestMemo.has(key)) {
    const q = new URLSearchParams({ per_page: "1" });
    if (ref) q.set("sha", ref);
    if (subpath) q.set("path", subpath);
    if (CUTOFF) q.set("until", CUTOFF.toISOString());
    latestMemo.set(key, gh(`/repos/${repo}/commits?${q}`).then(list => list[0]?.sha || null));
  }
  return latestMemo.get(key);
}

// True when `head` already contains `base` (head is the same commit or newer).
async function contains(repo, base, head) {
  const c = await gh(`/repos/${repo}/compare/${base}...${head}`);
  return c.status === "identical" || c.status === "ahead";
}

async function syncSource(name, src) {
  if (!src || typeof src !== "object" || !src.sha) return;
  const repo = repoOf(src);
  if (!repo) return;
  const subpath = src.source === "git-subdir" ? src.path : null;
  const next = await latestCommit(repo, src.ref, subpath);
  if (!next || next === src.sha) return;
  // The pin may already be newer than the latest commit touching `path`
  // (or newer than the MIN_AGE_DAYS cutoff); keep it in that case.
  if (await contains(repo, next, src.sha)) return;
  changes.push(`${name}: ${repo}${subpath ? "/" + subpath : ""} ${src.sha.slice(0, 7)} -> ${next.slice(0, 7)}`);
  src.sha = next;
}

const npmMemo = new Map();
async function latestNpm(pkg) {
  if (!npmMemo.has(pkg)) {
    const url = `https://registry.npmjs.org/${pkg.replace("/", "%2f")}`;
    npmMemo.set(
      pkg,
      getJson(url).then(meta => {
        if (!CUTOFF) return meta["dist-tags"]?.latest || null;
        const stable = Object.entries(meta.time || {})
          .filter(([v, t]) => /^\d+\.\d+\.\d+$/.test(v) && new Date(t) <= CUTOFF)
          .sort((a, b) => new Date(a[1]) - new Date(b[1]));
        return stable.length ? stable[stable.length - 1][0] : null;
      }),
    );
  }
  return npmMemo.get(pkg);
}

const PINNED = /^(@?[a-z0-9][\w.-]*(?:\/[\w.-]+)?)@(\d+\.\d+\.\d+)$/i;
async function syncMcpServers(label, servers) {
  for (const [srv, cfg] of Object.entries(servers || {})) {
    const args = cfg?.args || [];
    for (let i = 0; i < args.length; i++) {
      const m = PINNED.exec(args[i]);
      if (!m) continue;
      const [, pkg, cur] = m;
      const next = await latestNpm(pkg);
      if (!next || next === cur) continue;
      changes.push(`${label} (${srv}): ${pkg} ${cur} -> ${next}`);
      args[i] = `${pkg}@${next}`;
    }
  }
}

async function guarded(label, fn) {
  try {
    await fn();
  } catch (e) {
    failures.push(`${label}: ${e.message}`);
  }
}

const market = JSON.parse(fs.readFileSync(MARKETPLACE, "utf8"));
await Promise.all(
  market.plugins.map(p =>
    guarded(p.name, async () => {
      await syncSource(p.name, p.source);
      await syncMcpServers(p.name, p.mcpServers);
    }),
  ),
);

const localMcp = [];
const pluginsDir = path.join(ROOT, "plugins");
if (fs.existsSync(pluginsDir)) {
  for (const dir of fs.readdirSync(pluginsDir)) {
    const file = path.join(pluginsDir, dir, ".mcp.json");
    if (!fs.existsSync(file)) continue;
    const json = JSON.parse(fs.readFileSync(file, "utf8"));
    const before = JSON.stringify(json);
    await guarded(`plugins/${dir}`, () => syncMcpServers(`plugins/${dir}`, json.mcpServers || json));
    if (JSON.stringify(json) !== before) localMcp.push([file, json]);
  }
}

console.log(changes.length ? changes.join("\n") : "All pins are up to date.");
if (failures.length) console.error("Could not check:\n" + failures.join("\n"));

if (!DRY && changes.length) {
  fs.writeFileSync(MARKETPLACE, JSON.stringify(market, null, 2) + "\n");
  for (const [file, json] of localMcp) fs.writeFileSync(file, JSON.stringify(json, null, 2) + "\n");
}
if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `changed=${changes.length > 0}\n`);
// A failed lookup leaves that pin unchanged; fail the run only when nothing could be checked.
process.exitCode = failures.length && failures.length === market.plugins.length ? 1 : 0;
