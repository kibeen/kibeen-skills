// apply-settings.mjs against a throwaway config directory. The `claude` CLI is kept off PATH,
// so only the settings merge and the CLAUDE.md block run (no network, no plugin changes).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(ROOT, "scripts", "apply-settings.mjs");
const fragment = JSON.parse(fs.readFileSync(path.join(ROOT, "settings", "claude-settings.json"), "utf8"));
const catalog = JSON.parse(fs.readFileSync(path.join(ROOT, ".claude-plugin", "marketplace.json"), "utf8"));

function machine(settings) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "apply-settings-"));
  const emptyBin = path.join(dir, "bin");
  fs.mkdirSync(emptyBin);
  if (settings) fs.writeFileSync(path.join(dir, "settings.json"), JSON.stringify(settings));
  const run = (...args) =>
    spawnSync(process.execPath, [SCRIPT, ...args], {
      encoding: "utf8",
      env: { PATH: emptyBin, CLAUDE_CONFIG_DIR: dir, HOME: dir },
    });
  const read = () => JSON.parse(fs.readFileSync(path.join(dir, "settings.json"), "utf8"));
  const memo = () => fs.readFileSync(path.join(dir, "CLAUDE.md"), "utf8");
  return { dir, run, read, memo };
}

test("a fresh machine gets the plugins, the output style and the instruction block", () => {
  const m = machine();
  const r = m.run();
  assert.equal(r.status, 0, r.stderr);
  const s = m.read();
  assert.equal(s.outputStyle, fragment.outputStyle);
  assert.deepEqual(s.enabledPlugins, fragment.enabledPlugins);
  assert.match(m.memo(), /<!-- BEGIN kibeen-skills/);
  assert.equal(m.run("--check").status, 0, "a second run finds nothing to change");
});

test("an output style chosen on the machine is kept", () => {
  const m = machine({ outputStyle: "Explanatory" });
  const r = m.run();
  assert.equal(m.read().outputStyle, "Explanatory");
  assert.match(r.stdout, /outputStyle: kept Explanatory/);
  assert.equal(m.run("--check").status, 0, "a kept style is not reported as a difference");
});

test("--marketplaces-only leaves plugins and the output style alone", () => {
  const m = machine({ theme: "dark" });
  m.run("--marketplaces-only");
  const s = m.read();
  assert.equal(s.outputStyle, undefined);
  assert.deepEqual(s.enabledPlugins, {});
  assert.equal(s.theme, "dark");
  assert.deepEqual(Object.keys(s.extraKnownMarketplaces), Object.keys(fragment.extraKnownMarketplaces));
});

test("settings entries for plugins that left the catalog are dropped, others stay", () => {
  const gone = `no-longer-here@${catalog.name}`;
  const m = machine({ enabledPlugins: { [gone]: true, "someone-else@other-market": true } });
  assert.equal(m.run("--check").status, 2);
  m.run();
  const s = m.read();
  assert.equal(gone in s.enabledPlugins, false);
  assert.equal(s.enabledPlugins["someone-else@other-market"], true);
});

test("a plugin switched off on the machine stays off", () => {
  const id = Object.keys(fragment.enabledPlugins)[0];
  const m = machine({ enabledPlugins: { [id]: false } });
  m.run();
  assert.equal(m.read().enabledPlugins[id], false);
});

test("the catalog, the bundle's dependencies and enabledPlugins name the same plugins", () => {
  const bundle = JSON.parse(
    fs.readFileSync(path.join(ROOT, "plugins", "kibeen-skills", ".claude-plugin", "plugin.json"), "utf8"),
  );
  assert.deepEqual([...bundle.dependencies].sort(), Object.keys(fragment.enabledPlugins).sort());
  const inCatalog = new Set(catalog.plugins.map(p => `${p.name}@${catalog.name}`));
  for (const id of bundle.dependencies.filter(d => d.endsWith(`@${catalog.name}`)))
    assert.ok(inCatalog.has(id), `${id} is a dependency but not in marketplace.json`);
});
