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


def below_floor_versions(line, floor):
    """Versions named on `line` that sit below `floor`.

    The repo-wide guard and its own spelling regression both go through this,
    so narrowing the matching cannot leave the regression test green - the
    previous version copied the regex and passed against a reverted guard.
    """
    lowered = line.lower()
    if "python" not in lowered and not re.search(r"requires?\s+\d+\.\d+", lowered):
        return []
    found = re.findall(r"(\d+)\.(\d+)", line)
    found += re.findall(r"python(\d)(\d+)", line, re.IGNORECASE)
    return [(int(a), int(b)) for a, b in found if (int(a), int(b)) < tuple(floor)]

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

    def test_the_hooks_json_parses_and_runs_the_hook_script(self):
        """CI parsed this file in a job of its own, with the locale's default
        encoding. Reading it here gets both OSes and explicit utf-8, and lets
        the command be checked rather than only the syntax."""
        path = ROOT / "plugins" / "kibeen-skills" / "hooks" / "hooks.json"
        hooks = json.loads(path.read_text(encoding="utf-8"))
        entries = hooks["hooks"]["SessionStart"]
        commands = [h["command"] for e in entries for h in e["hooks"]]
        self.assertTrue(commands, "SessionStart runs nothing")
        for command in commands:
            self.assertIn("hooks/sync_settings.py", command)
            self.assertIn(
                "python3", command,
                "a machine with no `python` on PATH needs the python3 fallback",
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
        """One source of truth. Any other file naming a lower version can drift
        from it silently, which is exactly what happened with 3.9.

        Scans every tracked text file rather than a hardcoded list, and matches
        "Python 3.9", "python3.9" and "Python3.9" alike - a guard that only
        catches the spelling I happened to think of is not a guard.
        """
        floor = self.rt.floor_str()
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True,
        ).stdout.decode("utf-8").split(chr(0))
        scanned = 0
        for rel in [r for r in tracked if r.endswith((".md", ".py", ".json", ".yml", ".yaml"))]:
            if rel in ("tests/test_apply_settings.py", "scripts/_runtime.py"):
                continue  # these name low versions on purpose
            try:
                text = (ROOT / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            for lineno, line in enumerate(text.split(chr(10)), 1):
                for major, minor in below_floor_versions(line, self.rt.MIN_PYTHON):
                    self.fail(
                        "%s:%d names %d.%d, below the declared floor %s; update "
                        "MIN_PYTHON in scripts/_runtime.py instead of hardcoding "
                        "a version%s  %s" % (rel, lineno, major, minor, floor,
                                             chr(10), line.strip())
                    )
        self.assertGreater(scanned, 3, "the scan found almost no files to check")

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


class SyncWorkflowGuardTest(unittest.TestCase):
    """sync-upstream.yml pushes to main with credentials that start no
    workflow run, so the step it runs itself is the only thing standing
    between a bumped pin and the default branch. Nothing else in this repo
    would notice if that step were dropped, reordered after the push, or
    left collecting zero tests."""

    def setUp(self):
        path = ROOT / ".github" / "workflows" / "sync-upstream.yml"
        self.lines = path.read_text(encoding="utf-8").split(chr(10))

    def _first(self, pattern):
        for i, line in enumerate(self.lines):
            if re.search(pattern, line):
                return i
        return None

    def test_the_suite_runs_before_the_push(self):
        tested = self._first(r"unittest discover")
        pushed = self._first(r"^\s*git push")
        self.assertIsNotNone(tested, "the sync workflow pushes to main untested")
        self.assertIsNotNone(pushed, "expected a git push in the sync workflow")
        self.assertLess(
            tested, pushed,
            "the test step must come before the push, or the bot commit lands "
            "on main before anything has checked it",
        )

    def test_the_push_is_guarded_against_an_empty_suite(self):
        self.assertIsNotNone(
            self._first(r"countTestCases"),
            "discover exits 0 on an empty suite, so the push needs the same "
            "collection guard tests.yml uses",
        )


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

def load_runtime_with_floor(floor, tmpdir):
    """Import a copy of _runtime.py with MIN_PYTHON replaced."""
    import importlib.util
    src = (ROOT / "scripts" / "_runtime.py").read_text(encoding="utf-8")
    src = src.replace("MIN_PYTHON = (3, 11)", "MIN_PYTHON = " + repr(floor))
    path = Path(tmpdir) / "rt_variant.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("rt_variant", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeCheckout:
    """A throwaway marketplace checkout the hook will find, with a stand-in
    apply_settings.py, so every hook path can be driven without touching the
    real settings."""

    def __init__(self, child_src, floor=None, child_timeout=None):
        self.child_timeout = child_timeout
        self._tmp = tempfile.TemporaryDirectory(prefix="hook-")
        self.dir = Path(self._tmp.name)
        root = self.dir / "plugins" / "marketplaces" / "kibeen-skills"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "apply_settings.py").write_text(child_src, encoding="utf-8")
        rt = (ROOT / "scripts" / "_runtime.py").read_text(encoding="utf-8")
        if floor is not None:
            rt = rt.replace("MIN_PYTHON = (3, 11)", "MIN_PYTHON = " + repr(floor))
        (root / "scripts" / "_runtime.py").write_text(rt, encoding="utf-8")
        # a non-empty HEAD, so the 24h back-off is actually in play
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").write_text("abcdef01" * 5, encoding="utf-8")
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "CLAUDE_CONFIG_DIR": str(self.dir),
            "HOME": str(self.dir),
            "USERPROFILE": str(self.dir),
        }
        for key in ("SYSTEMROOT", "SystemRoot", "SystemDrive", "ProgramData",
                    "COMSPEC", "PATHEXT", "TEMP", "TMP"):
            if key in os.environ:
                self.env[key] = os.environ[key]

    def cleanup(self):
        self._tmp.cleanup()

    def run(self):
        src = (ROOT / "plugins" / "kibeen-skills" / "hooks" / "sync_settings.py").read_text(
            encoding="utf-8")
        if self.child_timeout is not None:
            src = src.replace("CHILD_TIMEOUT_S = 90",
                              "CHILD_TIMEOUT_S = %d" % self.child_timeout)
        hook = self.dir / "hook_under_test.py"
        hook.write_text(src, encoding="utf-8", newline=chr(10))
        return subprocess.run(
            [sys.executable, str(hook)],
            capture_output=True, text=True, encoding="utf-8", env=self.env,
        )

    @property
    def stamp(self):
        f = self.dir / "plugins" / "data" / "kibeen-skills" / "last-sync-user.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    @property
    def error_log(self):
        return self.dir / "plugins" / "data" / "kibeen-skills" / "last-error.log"


class InterpreterSurveyTest(unittest.TestCase):
    """New behaviour in this change: pick an interpreter that meets the floor."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts")))
        import _runtime
        self.rt = _runtime

    def test_a_satisfied_machine_spawns_nothing(self):
        argv, found = self.rt.survey()
        self.assertEqual(argv, [sys.executable])
        self.assertEqual(found, tuple(sys.version_info[:2]))

    def test_candidates_come_from_the_floor_newest_first(self):
        names = [c[0] for c in self.rt.candidates()]
        major, minor = self.rt.MIN_PYTHON
        self.assertEqual(names[0], "python%d.%d" % (major, minor + 3))
        self.assertIn("python%d.%d" % (major, minor), names)
        self.assertEqual(names[-3:], ["python%d" % major, "python", "py"])
        for name in names:
            if name.startswith("python%d." % major):
                self.assertGreaterEqual(int(name.split(".")[1]), minor,
                                        "nothing below the floor is ever probed")

    def test_an_unreachable_floor_reports_the_best_version_found(self):
        """The message must describe the machine, not the running interpreter."""
        with tempfile.TemporaryDirectory() as d:
            rt = load_runtime_with_floor((99, 0), d)
            argv, best = rt.survey()
        self.assertIsNone(argv)
        self.assertEqual(best, tuple(sys.version_info[:2]))

    def test_a_missing_interpreter_probes_to_none(self):
        self.assertIsNone(self.rt._probe(["definitely-not-a-python-xyz"]))

    def test_the_probe_budget_fits_the_hook_timeout(self):
        """Everything the hook may spend before giving up has to fit inside the
        SessionStart timeout, including locating the marketplace through the
        claude CLI - which the earlier version of this test left out."""
        hook_src = (ROOT / "plugins" / "kibeen-skills" / "hooks" / "sync_settings.py").read_text(
            encoding="utf-8")

        def const(name):
            return int(re.search(name + r" = (\d+)", hook_src).group(1))

        probes = len(self.rt.candidates()) * self.rt.PROBE_TIMEOUT_S
        worst = const("CLI_PROBE_TIMEOUT_S") + probes + const("CHILD_TIMEOUT_S")
        self.assertLess(
            worst, const("HOOK_TIMEOUT_S"),
            "cli %ds + probes %ds + child %ds" % (
                const("CLI_PROBE_TIMEOUT_S"), probes, const("CHILD_TIMEOUT_S")),
        )

    def test_an_older_running_interpreter_is_replaced_by_a_candidate(self):
        """The whole point: a machine whose `python` is too old still syncs
        through a newer install."""
        with tempfile.TemporaryDirectory() as d:
            rt = load_runtime_with_floor((99, 1), d)
            calls = []

            def fake_probe(argv):
                calls.append(argv[0])
                return (99, 1) if argv[0] == "python99.1" else (3, 8)

            rt._probe = fake_probe
            argv, found = rt.survey()
        self.assertEqual(argv, ["python99.1"])
        self.assertEqual(found, (99, 1))
        self.assertEqual(calls[0], "python99.4", "newest candidate is tried first")

    def test_the_drift_guard_catches_the_spellings_ci_files_use(self):
        """Drives the guard helper itself, not a copy of its regex."""
        floor_major, floor_minor = self.rt.MIN_PYTHON
        low = "%d.%d" % (floor_major, floor_minor - 2)
        for line in (
            "python" + low + " is required",
            "sudo dnf install python" + low.replace(".", ""),
            '  python-version: "' + low + '"',
            "PYTHON_VERSION=" + low,
            "Python " + low + "+",
            "requires " + low + "+",
        ):
            with self.subTest(line=line):
                self.assertTrue(
                    below_floor_versions(line, self.rt.MIN_PYTHON),
                    "the guard would not flag this spelling",
                )

    def test_the_guard_does_not_flag_unrelated_numbers(self):
        for line in ("version 1.2 of the spec", "see section 3.9 below",
                     "Python " + self.rt.floor_str(), "timeout 2.5 seconds"):
            with self.subTest(line=line):
                self.assertEqual(below_floor_versions(line, self.rt.MIN_PYTHON), [])


class HookFailurePathTest(unittest.TestCase):
    """Every case here exited 0 with no output before this change, which is how
    four defects shipped: the real work happens in the child process."""

    def checkout(self, child_src, floor=None, child_timeout=None):
        c = FakeCheckout(child_src, floor, child_timeout)
        self.addCleanup(c.cleanup)
        return c

    def test_a_child_that_exits_nonzero_is_logged_and_announced(self):
        c = self.checkout("import sys\nsys.stderr.write('Traceback: boom')\nsys.exit(1)\n")
        r = c.run()
        self.assertEqual(r.returncode, 0, "a failed sync must never block a session")
        self.assertIn("systemMessage", r.stdout)
        self.assertTrue(c.error_log.exists())
        log = c.error_log.read_text(encoding="utf-8")
        self.assertIn("exited 1", log)
        self.assertIn("boom", log, "the child stderr is the only copy of its traceback")

    def test_a_failed_sync_is_retried_next_session(self):
        c = self.checkout("import sys; sys.exit(1)\n")
        c.run()
        self.assertIsNone(c.stamp.get("sha"),
                          "with a sha recorded, fixing the cause would wait 24h")
        self.assertEqual(c.stamp.get("mode"), "failed")

    def test_the_failure_notice_is_not_repeated_every_session(self):
        c = self.checkout("import sys; sys.exit(1)\n")
        self.assertIn("systemMessage", c.run().stdout)
        self.assertNotIn("systemMessage", c.run().stdout, "once a day, not every session")
        self.assertIsNone(c.stamp.get("sha"), "throttling the notice must not stop the retry")

    def test_exit_2_means_differences_found_not_failure(self):
        """Check mode uses exit 2 for "something differs". Treating that as a
        crash would cry wolf on every machine with pending changes."""
        c = self.checkout("import sys; sys.exit(2)\n")
        r = c.run()
        self.assertNotIn("systemMessage", r.stdout)
        self.assertFalse(c.error_log.exists())
        self.assertTrue(c.stamp.get("sha"), "a clean run records the sha and backs off")

    def test_no_new_enough_python_skips_with_an_actionable_message(self):
        c = self.checkout("import sys; sys.exit(0)\n", floor=(99, 0))
        r = c.run()
        self.assertEqual(r.returncode, 0)
        payload = json.loads(r.stdout)
        self.assertIn("99.0", payload["systemMessage"])
        self.assertEqual(c.stamp.get("mode"), "python-too-old")
        self.assertIsNone(c.stamp.get("sha"),
                          "installing Python must recover on the next session")
    def test_a_timed_out_child_is_a_failure_not_a_success(self):
        """Its status is None, which used to slip past the non-zero check and
        land in the success branch: stamped as applied, nothing logged, and
        then silent for 24h. apply_settings runs `claude plugin install` as its
        own child, so a hang there means half-applied settings."""
        c = self.checkout("import sys,time\n"
                          "sys.stderr.write('slow'); sys.stderr.flush()\n"
                          "time.sleep(30)\n",
                          child_timeout=2)
        r = c.run()
        self.assertEqual(r.returncode, 0)
        self.assertIn("systemMessage", r.stdout)
        self.assertEqual(c.stamp.get("mode"), "timeout")
        self.assertTrue(c.error_log.exists())
        log = c.error_log.read_text(encoding="utf-8")
        self.assertIn("timed out", log)
        self.assertIn("slow", log, "whatever it said before being killed is the only clue")

    def test_a_timeout_backs_off_so_it_does_not_delay_every_session(self):
        """Unlike a fast failure, retrying this costs the full timeout each
        time, so the sha is kept and the next attempt waits."""
        c = self.checkout("import time; time.sleep(30)\n", child_timeout=2)
        c.run()
        self.assertTrue(c.stamp.get("sha"))

    def test_the_child_own_failure_message_reaches_the_user(self):
        """apply_settings.fail() writes a hook message naming what the user has
        to do - missing claude CLI, unparseable settings.json. Replacing it
        with "see the log" buries the only actionable part, which main did not
        do."""
        c = self.checkout(
            "import json,sys\n"
            'sys.stdout.write(json.dumps({"systemMessage": "SENTINEL act on this"}))\n'
            "sys.exit(1)\n"
        )
        r = c.run()
        self.assertIn("SENTINEL act on this", r.stdout)
        self.assertTrue(c.error_log.exists(), "still logged for diagnosis")

    def test_a_corrupt_stamp_cannot_abort_the_session(self):
        """The stamp is read before the guarded block, so anything unreadable
        there used to escape as a raw traceback or be swallowed forever."""
        for payload in (b"[]", b"\xff\xfe not utf-8", b"{truncated"):
            with self.subTest(payload=payload[:12]):
                c = self.checkout("import sys; sys.exit(0)\n")
                stamp = c.dir / "plugins" / "data" / "kibeen-skills"
                stamp.mkdir(parents=True, exist_ok=True)
                (stamp / "last-sync-user.json").write_bytes(payload)
                r = c.run()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stderr, "", "no raw traceback may reach the user")
                self.assertTrue(c.stamp.get("sha"), "the run still completes and stamps")
    def test_a_slow_failure_is_not_retried_every_session(self):
        """A child that fails slowly would otherwise add its cost to every
        session start, with the notice throttled to once a day - a silent
        regression against main, which backed off after any attempt."""
        c = self.checkout("import sys,time\ntime.sleep(6)\nsys.exit(1)\n")
        c.run()
        self.assertEqual(c.stamp.get("mode"), "failed")
        self.assertTrue(c.stamp.get("sha"), "a slow failure must back off")

    def test_a_fast_failure_is_still_retried_next_session(self):
        """The common causes - missing claude CLI, unparseable settings.json -
        fail in well under a second, so fixing them takes effect at once."""
        c = self.checkout("import sys; sys.exit(1)\n")
        c.run()
        self.assertIsNone(c.stamp.get("sha"))

if __name__ == "__main__":
    unittest.main()
