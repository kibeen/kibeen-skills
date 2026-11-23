"""scripts/sync_upstream.py against a throwaway repo tree and a scripted fetch.

No network: every GitHub and npm response comes from FakeUpstream, which also
records what was asked, so the query a lookup sends is checked along with what
it does with the answer.

Run: python -m unittest discover -s tests
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sync_upstream  # noqa: E402

OLD = "1" * 40
NEW = "2" * 40


class FakeUpstream:
    """Answers by URL path; a value that is an Exception is raised instead."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, headers: dict):
        self.calls.append((url, headers))
        parts = urlsplit(url)
        key = parts.netloc + parts.path
        if key not in self.routes:
            raise sync_upstream.LookupFailed("404 Not Found " + url)
        answer = self.routes[key]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def query(self, path_suffix: str) -> dict:
        for url, _ in self.calls:
            if urlsplit(url).path.endswith(path_suffix):
                return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        raise AssertionError("no call to ..." + path_suffix)


def commits(repo, sha):
    return {"api.github.com/repos/%s/commits" % repo: [{"sha": sha}]}


def compare(repo, base, head, status):
    return {"api.github.com/repos/%s/compare/%s...%s" % (repo, base, head): {"status": status}}


class Tree:
    """A repo checkout holding only what the script reads and writes."""

    def __init__(self, plugins: list, local_mcp: dict | None = None):
        self._tmp = tempfile.TemporaryDirectory(prefix="sync-upstream-")
        self.root = Path(self._tmp.name)
        (self.root / ".claude-plugin").mkdir()
        self.market = self.root / ".claude-plugin" / "marketplace.json"
        sync_upstream.write_json(self.market, {"name": "kibeen-skills", "plugins": plugins})
        for name, data in (local_mcp or {}).items():
            d = self.root / "plugins" / name
            d.mkdir(parents=True)
            sync_upstream.write_json(d / ".mcp.json", data)
        self.output = self.root / "github-output"

    def cleanup(self):
        self._tmp.cleanup()

    def run(self, fetch, *argv, **env):
        env = {"GITHUB_OUTPUT": str(self.output), **env}
        # keep the script's report out of the suite's own output
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return sync_upstream.main(list(argv), env, self.root, fetch)

    def read(self, rel=".claude-plugin/marketplace.json"):
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def changed(self):
        return self.output.read_text(encoding="utf-8")


def subdir_plugin(name="doc", sha=OLD, path="skills/doc"):
    return {"name": name, "source": {
        "source": "git-subdir", "url": "https://github.com/up/skills.git", "path": path, "sha": sha}}


class SyncUpstreamTest(unittest.TestCase):
    def tree(self, plugins, local_mcp=None):
        t = Tree(plugins, local_mcp)
        self.addCleanup(t.cleanup)
        return t

    def test_a_pin_moves_to_the_latest_commit_that_touched_its_folder(self):
        t = self.tree([subdir_plugin()])
        up = FakeUpstream({**commits("up/skills", NEW), **compare("up/skills", NEW, OLD, "behind")})
        self.assertEqual(t.run(up), 0)
        self.assertEqual(t.read()["plugins"][0]["source"]["sha"], NEW)
        self.assertEqual(up.query("/commits"), {"per_page": "1", "path": "skills/doc"})
        self.assertEqual(t.changed(), "changed=true\n")

    def test_a_pin_already_newer_than_that_commit_is_kept(self):
        """The latest commit touching `path` can be older than the pin."""
        t = self.tree([subdir_plugin()])
        up = FakeUpstream({**commits("up/skills", NEW), **compare("up/skills", NEW, OLD, "ahead")})
        self.assertEqual(t.run(up), 0)
        self.assertEqual(t.read()["plugins"][0]["source"]["sha"], OLD)
        self.assertEqual(t.changed(), "changed=false\n")

    def test_a_github_source_follows_its_ref_and_sends_the_token(self):
        t = self.tree([{"name": "gh", "source": {
            "source": "github", "repo": "up/tool", "ref": "stable", "sha": OLD}}])
        up = FakeUpstream({**commits("up/tool", NEW), **compare("up/tool", NEW, OLD, "behind")})
        t.run(up, GITHUB_TOKEN="tkn")
        self.assertEqual(up.query("/commits"), {"per_page": "1", "sha": "stable"})
        self.assertEqual(up.calls[0][1].get("Authorization"), "Bearer tkn")
        self.assertEqual(t.read()["plugins"][0]["source"]["sha"], NEW)

    def test_a_source_without_a_pin_is_not_looked_up(self):
        """The script moves pins; it does not add one to an entry that has none."""
        t = self.tree([{"name": "loop", "source": {"source": "github", "repo": "up/loop"}},
                       {"name": "local", "source": "./plugins/local"}])
        up = FakeUpstream({})
        self.assertEqual(t.run(up), 0)
        self.assertEqual(up.calls, [])

    def test_dry_run_reports_and_writes_nothing(self):
        t = self.tree([subdir_plugin()])
        before = t.market.read_bytes()
        up = FakeUpstream({**commits("up/skills", NEW), **compare("up/skills", NEW, OLD, "behind")})
        self.assertEqual(t.run(up, "--dry-run"), 0)
        self.assertEqual(t.market.read_bytes(), before)

    def test_an_npm_pin_moves_to_latest_and_a_scoped_name_is_encoded(self):
        t = self.tree([{"name": "pw", "source": "./plugins/pw", "mcpServers": {"pw": {
            "command": "npx", "args": ["-y", "@scope/mcp@1.0.0", "other@latest"]}}}])
        up = FakeUpstream({"registry.npmjs.org/@scope%2fmcp": {"dist-tags": {"latest": "1.4.2"}}})
        t.run(up)
        self.assertEqual(t.read()["plugins"][0]["mcpServers"]["pw"]["args"],
                         ["-y", "@scope/mcp@1.4.2", "other@latest"])
        self.assertEqual(len(up.calls), 1, "an unpinned arg must not be looked up")

    def test_local_mcp_files_are_bumped_in_both_layouts(self):
        wrapped = {"mcpServers": {"a": {"command": "npx", "args": ["pkg-a@1.0.0"]}}}
        bare = {"b": {"command": "npx", "args": ["pkg-b@2.0.0"]}}
        t = self.tree([], {"one": wrapped, "two": bare})
        up = FakeUpstream({"registry.npmjs.org/pkg-a": {"dist-tags": {"latest": "1.1.0"}},
                           "registry.npmjs.org/pkg-b": {"dist-tags": {"latest": "2.2.0"}}})
        t.run(up)
        self.assertEqual(t.read("plugins/one/.mcp.json")["mcpServers"]["a"]["args"], ["pkg-a@1.1.0"])
        self.assertEqual(t.read("plugins/two/.mcp.json")["b"]["args"], ["pkg-b@2.2.0"])

    def test_min_age_days_holds_back_recent_commits_and_releases(self):
        now = datetime.now(timezone.utc)
        t = self.tree([subdir_plugin(),
                       {"name": "pw", "source": "./plugins/pw",
                        "mcpServers": {"pw": {"args": ["pkg@1.0.0"]}}}])
        up = FakeUpstream({
            **commits("up/skills", NEW), **compare("up/skills", NEW, OLD, "behind"),
            "registry.npmjs.org/pkg": {"dist-tags": {"latest": "1.3.0"}, "time": {
                "created": "2020-01-01T00:00:00.000Z",
                "1.1.0": "2020-01-02T00:00:00.000Z",
                "1.2.0": "2020-01-03T00:00:00.000Z",
                "2.0.0-beta.1": "2020-01-04T00:00:00.000Z",
                "1.3.0": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }},
        })
        t.run(up, MIN_AGE_DAYS="3")
        until = datetime.fromisoformat(up.query("/commits")["until"].replace("Z", "+00:00"))
        self.assertAlmostEqual((now - until).total_seconds(), 3 * 86400, delta=60)
        self.assertEqual(t.read()["plugins"][1]["mcpServers"]["pw"]["args"], ["pkg@1.2.0"],
                         "newest stable release older than the cutoff, not latest or a beta")

    def test_a_malformed_min_age_days_stops_before_any_lookup(self):
        """Number("3d") was NaN, which the Node version read as "no delay"."""
        for bad in ("3d", "-1", "nan", "inf", "1e9"):
            with self.subTest(value=bad):
                t = self.tree([subdir_plugin()])
                up = FakeUpstream({})
                self.assertEqual(t.run(up, MIN_AGE_DAYS=bad), 1)
                self.assertEqual(up.calls, [])

    def test_an_empty_or_zero_min_age_days_means_no_delay(self):
        for value in ("", "0", " 0 "):
            with self.subTest(value=value):
                self.assertIsNone(sync_upstream.cutoff_from(value))

    def test_one_failed_lookup_leaves_that_pin_and_the_run_passes(self):
        t = self.tree([subdir_plugin("broken", path="gone"),
                       {"name": "ok", "source": {"source": "github", "repo": "up/tool", "sha": OLD}}])
        up = FakeUpstream({**commits("up/tool", NEW), **compare("up/tool", NEW, OLD, "behind")})
        up.routes["api.github.com/repos/up/skills/commits"] = sync_upstream.LookupFailed("503 x")
        self.assertEqual(t.run(up), 0)
        plugins = t.read()["plugins"]
        self.assertEqual(plugins[0]["source"]["sha"], OLD)
        self.assertEqual(plugins[1]["source"]["sha"], NEW)

    def test_the_run_fails_when_nothing_could_be_checked(self):
        t = self.tree([subdir_plugin("a"), subdir_plugin("b")])
        up = FakeUpstream({"api.github.com/repos/up/skills/commits": OSError("network down")})
        self.assertEqual(t.run(up), 1)

    def test_entries_with_nothing_to_look_up_do_not_hide_a_run_where_every_lookup_failed(self):
        """The run used to fail only when the failures matched the number of
        catalog entries. A local folder or an unpinned source is an entry that
        is never looked up, so with one in the catalog the run passed while
        every lookup failed."""
        t = self.tree([{"name": "local", "source": "./plugins/local"},
                       {"name": "loop", "source": {"source": "github", "repo": "up/loop"}},
                       subdir_plugin(),
                       {"name": "pw", "source": "./plugins/pw",
                        "mcpServers": {"pw": {"args": ["pkg@1.0.0"]}}}],
                      {"one": {"mcpServers": {"a": {"args": ["pkg-a@1.0.0"]}}}})
        up = FakeUpstream({})
        self.assertEqual(t.run(up), 1)
        self.assertEqual(len(up.calls), 3, "the commit lookup and both npm lookups")

    def test_an_npm_lookup_that_worked_keeps_the_run_passing(self):
        """npm pins count as lookups too, so one that worked is a partial failure."""
        t = self.tree([subdir_plugin()], {"one": {"mcpServers": {"a": {"args": ["pkg-a@1.0.0"]}}}})
        up = FakeUpstream({"registry.npmjs.org/pkg-a": {"dist-tags": {"latest": "1.1.0"}}})
        self.assertEqual(t.run(up), 0)
        self.assertEqual(t.read("plugins/one/.mcp.json")["mcpServers"]["a"]["args"], ["pkg-a@1.1.0"])

    def test_a_failed_commit_lookup_still_lets_the_same_plugin_bump_its_npm_pin(self):
        """Each pin is its own lookup: one failing does not skip the next one."""
        t = self.tree([{**subdir_plugin(), "mcpServers": {"pw": {"args": ["pkg@1.0.0"]}}}])
        up = FakeUpstream({"registry.npmjs.org/pkg": {"dist-tags": {"latest": "1.2.0"}}})
        self.assertEqual(t.run(up), 0)
        plugin = t.read()["plugins"][0]
        self.assertEqual(plugin["source"]["sha"], OLD)
        self.assertEqual(plugin["mcpServers"]["pw"]["args"], ["pkg@1.2.0"])

    def test_the_daily_run_fails_when_every_lookup_of_the_real_catalog_fails(self):
        """The real catalog holds the local kibeen-skills folder beside its git
        sources, so this is the shape the daily workflow stayed green on."""
        real = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        t = self.tree(real["plugins"])
        up = FakeUpstream({})  # every route answers 404
        self.assertEqual(t.run(up), 1)
        self.assertTrue(up.calls, "the real catalog made no lookup to fail")

    def test_every_git_plugin_in_the_catalog_is_pinned_and_fetched_over_https(self):
        """pr-loop was a bare `github` entry with no sha. Nothing here moved it,
        and on a Windows PC with no SSH key it stayed three commits behind: Claude Code
        clones `github` sources over SSH when its SSH probe passes and does not
        fall back to HTTPS on a plugin update, so `claude plugin update` failed
        too. A `url` or `git-subdir` source with an https URL is cloned as
        written, and its sha is what this script bumps every day."""
        real = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        checked = 0
        for p in real["plugins"]:
            src = p.get("source")
            if not isinstance(src, dict):
                continue  # a folder inside this repo
            checked += 1
            with self.subTest(p["name"]):
                self.assertIn(src.get("source"), ("url", "git-subdir"))
                self.assertTrue(str(src.get("url")).startswith("https://"), src)
                self.assertRegex(str(src.get("sha")), r"\A[0-9a-f]{40}\Z")
                self.assertIsNotNone(sync_upstream.repo_of(src), "the daily bump cannot look it up")
        self.assertGreater(checked, 0, "the catalog has no git source to check")

    def test_the_daily_run_moves_every_git_plugin_of_the_real_catalog(self):
        real = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        pinned = {p["name"]: p["source"] for p in real["plugins"] if isinstance(p.get("source"), dict)}
        t = self.tree(real["plugins"])
        routes = {}
        for src in pinned.values():
            repo = sync_upstream.repo_of(src)
            routes.update({**commits(repo, NEW), **compare(repo, NEW, src["sha"], "behind")})
        self.assertEqual(t.run(FakeUpstream(routes)), 0)
        after = {p["name"]: p["source"]["sha"] for p in t.read()["plugins"] if p["name"] in pinned}
        self.assertEqual(after, {name: NEW for name in pinned})

    def test_a_bump_changes_only_the_pinned_line_of_the_real_catalog(self):
        """The written format has to match the committed file, or every bump
        would also reformat it."""
        real = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        pinned = [p for p in real["plugins"]
                  if isinstance(p.get("source"), dict) and p["source"].get("sha")]
        self.assertTrue(pinned, "the catalog has no pinned source to exercise")
        t = self.tree(real["plugins"])
        t.market.write_bytes((ROOT / ".claude-plugin" / "marketplace.json").read_bytes())
        src = pinned[0]["source"]
        repo = sync_upstream.repo_of(src)
        up = FakeUpstream({**commits(repo, NEW), **compare(repo, NEW, src["sha"], "behind")})
        t.run(up)
        before = (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8").split("\n")
        after = t.market.read_text(encoding="utf-8").split("\n")
        self.assertEqual(len(before), len(after))
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(changed), 1, changed)
        self.assertIn(NEW, changed[0][1])
        self.assertNotIn(b"\r\n", t.market.read_bytes())


if __name__ == "__main__":
    unittest.main()
