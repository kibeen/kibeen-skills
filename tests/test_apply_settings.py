"""apply_settings.py against a throwaway config directory. The `claude` CLI is kept off PATH,
so only the settings merge and the CLAUDE.md block run (no network, no plugin changes).

Run: python -m unittest discover -s tests
"""
from __future__ import annotations

import ast
import json
import os
import re
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
        # cmd.exe, the Windows loader and the shell cache need these; `claude`
        # stays unreachable because PATH holds only the empty bin dir. Without
        # SystemDrive/ProgramData, MSIX Python writes its icon cache into the
        # repo as "%SystemDrive%/ProgramData/..." - that debris got committed
        # once already.
        for key in (
            "SYSTEMROOT", "SystemRoot", "SystemDrive", "ProgramData",
            "COMSPEC", "PATHEXT", "TEMP", "TMP",
        ):
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


class HookPathTest(unittest.TestCase):
    """The --hook path and the hook script itself: the deployed code path.

    These cover the regressions the Node port introduced, all of which only
    show up through the hook, never through a plain run.
    """

    def machine(self, settings: dict | None = None) -> Machine:
        m = Machine(settings)
        self.addCleanup(m.cleanup)
        return m

    def test_hook_json_is_utf8_decodable_under_a_legacy_code_page(self):
        """The hook's parent reads this stream as UTF-8.

        Written in the console code page (cp949 on Korean Windows, cp1252 on
        English) the Korean systemMessage either mojibakes or raises, so the
        user gets a message of U+FFFD or no message at all.
        """
        m = self.machine()
        env = dict(m.env, PYTHONIOENCODING="cp949")
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--hook"],
            capture_output=True, env=env,  # bytes, not text: we assert on the encoding
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout.decode("utf-8"))  # must not raise
        self.assertIn("kibeen-skills", payload["systemMessage"])
        self.assertNotIn(chr(0xFFFD), payload["systemMessage"])

    def test_unparseable_settings_stop_the_run_and_are_left_alone(self):
        """Treating a broken settings.json as {} would drop every key the
        machine had and write a file holding only this repo's three."""
        NL = chr(10)
        broken = "{" + NL + '  "theme": "dark",' + NL + '  "model": "x",' + NL + "}"
        m = self.machine()
        target = m.dir / "settings.json"
        target.write_text(broken, encoding="utf-8")
        r = m.run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not valid JSON", r.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), broken)

    def test_a_utf8_bom_is_tolerated(self):
        m = self.machine()
        (m.dir / "settings.json").write_text(
            json.dumps({"theme": "dark"}), encoding="utf-8-sig"
        )
        r = m.run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(m.read()["theme"], "dark")

    def test_user_content_in_claude_md_survives_and_stays_lf(self):
        """README promises the text outside the markers is untouched. It
        must also not come back rewritten to CRLF (the old JS wrote LF)."""
        m = self.machine()
        memo = m.dir / "CLAUDE.md"
        NL = chr(10)
        head = "# My notes" + NL * 2 + "- one" + NL + "- two" + NL * 2
        memo.write_bytes(head.encode("utf-8"))
        m.run()
        after = memo.read_bytes()
        self.assertTrue(after.startswith(head.encode("utf-8")), after[:60])
        self.assertNotIn(bytes([13, 10]), after)

    def test_the_hook_script_emits_the_hook_json(self):
        """End-to-end through hooks/sync_settings.py, which locates the
        marketplace checkout and relays the child's stdout."""
        m = self.machine()
        root = m.dir / "plugins" / "marketplaces" / "kibeen-skills"
        for rel in (
            Path("scripts") / "apply_settings.py",
            Path("scripts") / "_runtime.py",
            Path("settings") / "claude-settings.json",
            Path("settings") / "CLAUDE.kibeen.md",
            Path(".claude-plugin") / "marketplace.json",
        ):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes((ROOT / rel).read_bytes())
        hook = ROOT / "plugins" / "kibeen-skills" / "hooks" / "sync_settings.py"
        r = subprocess.run(
            [sys.executable, str(hook)],
            capture_output=True, text=True, encoding="utf-8", env=m.env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout)
        self.assertIn("kibeen-skills", payload["systemMessage"])
        self.assertEqual(m.read()["outputStyle"], fragment["outputStyle"])
        stamp = m.dir / "plugins" / "data" / "kibeen-skills" / "last-sync-user.json"
        self.assertTrue(stamp.exists(), "a run must stamp, or it repeats every session")

    def test_settings_json_is_written_with_lf(self):
        """Node wrote LF. This file is the one the newline="" fix was missed on
        twice, so assert the bytes rather than trusting the call site."""
        m = self.machine()
        m.run()
        self.assertNotIn(bytes([13, 10]), (m.dir / "settings.json").read_bytes())


class RuntimeFloorTest(unittest.TestCase):
    """Guards against the failure this repo already shipped once: a declared
    Python floor that nothing ran, with a too-new API hiding behind it."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts")))
        import _runtime
        self.rt = _runtime

    def test_the_declared_floor_appears_nowhere_else_hardcoded(self):
        """One source of truth. Any other file naming a version can drift from
        it silently, which is exactly what happened with 3.9."""
        floor = self.rt.floor_str()
        pattern = re.compile(r"Python\s*(\d+\.\d+)")
        for rel in ("README.md",
                    "scripts/apply_settings.py",
                    "plugins/kibeen-skills/hooks/sync_settings.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for found in set(pattern.findall(text)):
                # An upgrade hint may name a newer version to install.
                if tuple(int(n) for n in found.split(".")) >= self.rt.MIN_PYTHON:
                    continue
                self.fail(
                    f"{rel} names Python {found}, below the declared floor "
                    f"{floor}; update scripts/_runtime.py instead of hardcoding"
                )

    def test_the_readme_states_the_declared_floor(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"Python {self.rt.floor_str()}+", readme)

    def test_the_guard_parses_on_pythons_it_must_reject(self):
        """A guard the rejected interpreter cannot parse never runs."""
        src = (ROOT / "scripts" / "_runtime.py").read_text(encoding="utf-8")
        for major, minor in ((3, 6), (3, 8), (3, 9)):
            ast.parse(src, feature_version=(major, minor))

    def test_meets_compares_against_the_floor(self):
        self.assertFalse(self.rt.meets((3, 9, 0)))
        self.assertTrue(self.rt.meets(self.rt.MIN_PYTHON + (0,)))

    def test_an_upgrade_hint_is_always_offered(self):
        hint = self.rt.upgrade_hint()
        self.assertTrue(hint.strip())
        self.assertIn(self.rt.floor_str(), self.rt.shortfall_message())
        self.assertIn(hint, self.rt.shortfall_message())

    def test_apply_settings_refuses_to_run_below_the_floor(self):
        """Raise the floor past the running interpreter and the script must
        stop with the hint, not start writing files."""
        m = Machine()
        self.addCleanup(m.cleanup)
        shim = m.dir / "shim"
        shim.mkdir()
        (shim / "_runtime.py").write_text(
            (ROOT / "scripts" / "_runtime.py").read_text(encoding="utf-8")
            .replace("MIN_PYTHON = (3, 11)", "MIN_PYTHON = (99, 0)"),
            encoding="utf-8",
        )
        (shim / "apply_settings.py").write_bytes(
            (ROOT / "scripts" / "apply_settings.py").read_bytes()
        )
        for rel in (Path("settings") / "claude-settings.json",
                    Path("settings") / "CLAUDE.kibeen.md",
                    Path(".claude-plugin") / "marketplace.json"):
            (m.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (m.dir / rel).write_bytes((ROOT / rel).read_bytes())
        r = subprocess.run(
            [sys.executable, str(shim / "apply_settings.py")],
            capture_output=True, text=True, encoding="utf-8", env=m.env,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("Python", r.stderr)
        self.assertFalse((m.dir / "settings.json").exists())


class HookVisibilityTest(unittest.TestCase):
    """The hook used to swallow every failure, so a broken sync looked healthy.
    Four defects shipped behind that."""

    def test_a_crashing_sync_is_logged_and_announced(self):
        m = Machine()
        self.addCleanup(m.cleanup)
        root = m.dir / "plugins" / "marketplaces" / "kibeen-skills"
        (root / "scripts").mkdir(parents=True)
        # present, so the hook proceeds - but broken, so the run raises
        (root / "scripts" / "apply_settings.py").write_text("x", encoding="utf-8")
        (root / "scripts" / "_runtime.py").write_text(
            "raise RuntimeError('boom')", encoding="utf-8"
        )
        hook = ROOT / "plugins" / "kibeen-skills" / "hooks" / "sync_settings.py"
        r = subprocess.run(
            [sys.executable, str(hook)],
            capture_output=True, text=True, encoding="utf-8", env=m.env,
        )
        self.assertEqual(r.returncode, 0, "a failed sync must never block a session")
        self.assertIn("systemMessage", r.stdout)
        log = m.dir / "plugins" / "data" / "kibeen-skills" / "last-error.log"
        self.assertTrue(log.exists(), "the traceback must be recoverable")
        self.assertIn("RuntimeError", log.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
