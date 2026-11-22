"""apply_settings.py against a throwaway config directory. The `claude` CLI is kept off PATH,
so only the settings merge and the CLAUDE.md block run (no network, no plugin changes).

Run: python -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "apply_settings.py"
fragment = json.loads((ROOT / "settings" / "claude-settings.json").read_text(encoding="utf-8"))
catalog = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))


class Machine:
    """A throwaway Claude config dir with no `claude` CLI reachable."""

    def __init__(self, settings: dict | None = None):
        self._tmp = tempfile.TemporaryDirectory(prefix="apply-settings-")
        self.dir = Path(self._tmp.name)
        empty_bin = self.dir / "bin"
        empty_bin.mkdir()
        if settings is not None:
            (self.dir / "settings.json").write_text(
                json.dumps(settings), encoding="utf-8"
            )
        self.env = {
            "PATH": str(empty_bin),
            "CLAUDE_CONFIG_DIR": str(self.dir),
            "HOME": str(self.dir),
            "USERPROFILE": str(self.dir),
        }
        # cmd.exe and the Windows loader still need these; `claude` stays unreachable.
        for key in ("SYSTEMROOT", "SystemRoot", "COMSPEC", "PATHEXT"):
            if key in os.environ:
                self.env[key] = os.environ[key]

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=self.env,
        )

    def read(self) -> dict:
        return json.loads((self.dir / "settings.json").read_text(encoding="utf-8"))

    def memo(self) -> str:
        return (self.dir / "CLAUDE.md").read_text(encoding="utf-8")


class ApplySettingsTest(unittest.TestCase):
    def machine(self, settings: dict | None = None) -> Machine:
        m = Machine(settings)
        self.addCleanup(m.cleanup)
        return m

    def test_fresh_machine_gets_plugins_style_and_instruction_block(self):
        m = self.machine()
        r = m.run()
        self.assertEqual(r.returncode, 0, r.stderr)
        s = m.read()
        self.assertEqual(s["outputStyle"], fragment["outputStyle"])
        self.assertEqual(s["enabledPlugins"], fragment["enabledPlugins"])
        self.assertIn("<!-- BEGIN kibeen-skills", m.memo())
        self.assertEqual(
            m.run("--check").returncode, 0, "a second run finds nothing to change"
        )

    def test_output_style_chosen_on_the_machine_is_kept(self):
        m = self.machine({"outputStyle": "Explanatory"})
        r = m.run()
        self.assertEqual(m.read()["outputStyle"], "Explanatory")
        self.assertIn("outputStyle: kept Explanatory", r.stdout)
        self.assertEqual(
            m.run("--check").returncode, 0, "a kept style is not reported as a difference"
        )

    def test_marketplaces_only_leaves_plugins_and_style_alone(self):
        m = self.machine({"theme": "dark"})
        m.run("--marketplaces-only")
        s = m.read()
        self.assertNotIn("outputStyle", s)
        self.assertEqual(s["enabledPlugins"], {})
        self.assertEqual(s["theme"], "dark")
        self.assertEqual(
            list(s["extraKnownMarketplaces"]), list(fragment["extraKnownMarketplaces"])
        )

    def test_entries_for_plugins_that_left_the_catalog_are_dropped(self):
        gone = f"no-longer-here@{catalog['name']}"
        m = self.machine(
            {"enabledPlugins": {gone: True, "someone-else@other-market": True}}
        )
        self.assertEqual(m.run("--check").returncode, 2)
        m.run()
        s = m.read()
        self.assertNotIn(gone, s["enabledPlugins"])
        self.assertTrue(s["enabledPlugins"]["someone-else@other-market"])

    def test_a_plugin_switched_off_on_the_machine_stays_off(self):
        plugin_id = next(iter(fragment["enabledPlugins"]))
        m = self.machine({"enabledPlugins": {plugin_id: False}})
        m.run()
        self.assertIs(m.read()["enabledPlugins"][plugin_id], False)

    def test_catalog_dependencies_and_enabled_plugins_agree(self):
        bundle = json.loads(
            (ROOT / "plugins" / "kibeen-skills" / ".claude-plugin" / "plugin.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(
            sorted(bundle["dependencies"]), sorted(fragment["enabledPlugins"])
        )
        in_catalog = {f"{p['name']}@{catalog['name']}" for p in catalog["plugins"]}
        for plugin_id in bundle["dependencies"]:
            if plugin_id.endswith(f"@{catalog['name']}"):
                self.assertIn(
                    plugin_id, in_catalog,
                    f"{plugin_id} is a dependency but not in marketplace.json",
                )


if __name__ == "__main__":
    unittest.main()
