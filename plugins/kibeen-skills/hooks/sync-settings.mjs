#!/usr/bin/env node
// SessionStart hook: bring this machine in line with the kibeen-skills settings.
// Runs when the kibeen-skills checkout has a new commit, or at most once a day otherwise.
// It applies every difference (installs, enables, removes) with a settings backup,
// and shows the user a one-line systemMessage of what it did. Nothing is added to the
// model's context. Set KIBEEN_AUTO_APPLY=0 to only be notified instead.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const INTERVAL_MS = 24 * 60 * 60 * 1000;
const configDir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
const dataDir = process.env.CLAUDE_PLUGIN_DATA || path.join(configDir, "plugins", "data", "kibeen-skills");
const stampFile = path.join(dataDir, "last-sync.json");
const autoApply = process.env.KIBEEN_AUTO_APPLY !== "0";

function marketplaceRoot() {
  const local = path.join(configDir, "plugins", "marketplaces", "kibeen-skills");
  if (fs.existsSync(path.join(local, "scripts", "apply-settings.mjs"))) return local;
  // Fall back to asking the CLI where the marketplace lives (e.g. a local-directory marketplace).
  const ls = spawnSync("claude", ["plugin", "marketplace", "list", "--json"], { encoding: "utf8", timeout: 10000 });
  const out = ls.stdout || "";
  const loc = JSON.parse(out.slice(out.indexOf("[")) || "[]").find(m => m.name === "kibeen-skills")?.installLocation;
  return loc && fs.existsSync(path.join(loc, "scripts", "apply-settings.mjs")) ? loc : null;
}

function headSha(root) {
  try {
    const head = fs.readFileSync(path.join(root, ".git", "HEAD"), "utf8").trim();
    if (!head.startsWith("ref: ")) return head;
    const ref = head.slice(5);
    const loose = path.join(root, ".git", ref);
    if (fs.existsSync(loose)) return fs.readFileSync(loose, "utf8").trim();
    const packed = fs.readFileSync(path.join(root, ".git", "packed-refs"), "utf8");
    return packed.split("\n").find(l => l.endsWith(" " + ref))?.split(" ")[0] || "";
  } catch {
    return "";
  }
}

try {
  const root = marketplaceRoot();
  if (!root) process.exit(0);
  const sha = headSha(root);
  const last = fs.existsSync(stampFile) ? JSON.parse(fs.readFileSync(stampFile, "utf8")) : {};
  if (sha && sha === last.sha && Date.now() - (last.at || 0) < INTERVAL_MS) process.exit(0);

  const args = [path.join(root, "scripts", "apply-settings.mjs"), "--hook", ...(autoApply ? [] : ["--check"])];
  const r = spawnSync(process.execPath, args, { encoding: "utf8", timeout: 110000 });
  fs.mkdirSync(dataDir, { recursive: true });
  fs.writeFileSync(stampFile, JSON.stringify({ at: Date.now(), sha, status: r.status, mode: autoApply ? "apply" : "check" }) + "\n");
  if (r.stdout && r.stdout.trim().startsWith("{")) process.stdout.write(r.stdout);
} catch {
  // A failed sync must never get in the way of starting a session.
}
process.exit(0);
