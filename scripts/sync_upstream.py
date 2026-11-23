#!/usr/bin/env python3
"""Bump the pinned upstream commits and npm versions in .claude-plugin/marketplace.json
(and plugins/*/.mcp.json) to the latest upstream release.

- github / url sources: sha -> latest commit on `ref` (default branch when unset).
- git-subdir sources:   sha -> latest commit that touched `path`, so a busy monorepo
  only moves a plugin when its own folder changed.
- npm args pinned as `pkg@x.y.z` in mcpServers: -> latest stable version.

Env: GITHUB_TOKEN or GH_TOKEN (recommended, raises the API rate limit),
     MIN_AGE_DAYS (default 0; only adopt commits/versions at least this many days old),
     GITHUB_OUTPUT (set by Actions; receives changed=true|false).
Usage: python scripts/sync_upstream.py [--dry-run]

Standard library only. It runs in .github/workflows/sync-upstream.yml, not on user
machines; it is Python so the repo has one runtime and one test suite. The minimum
Python version is declared once in scripts/_runtime.py and checked at startup.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _runtime  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HTTP_TIMEOUT_S = 30  # the workflow's 15-minute cap must not be spent on one stuck request

# re.ASCII keeps \w and \d to what the npm and GitHub names they match can contain.
PINNED = re.compile(r"(@?[a-z0-9][\w.-]*(?:/[\w.-]+)?)@(\d+\.\d+\.\d+)", re.IGNORECASE | re.ASCII)
STABLE = re.compile(r"\d+\.\d+\.\d+", re.ASCII)
GITHUB_REPO = re.compile(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?/?\Z")


class LookupFailed(Exception):
    pass


def http_get_json(url: str, headers: dict) -> object:
    req = Request(url, headers={"User-Agent": "kibeen-skills-sync", **headers})
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_S) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as e:
        raise LookupFailed("%s %s %s" % (e.code, e.reason, url)) from None


def cutoff_from(raw: str | None, now: datetime | None = None) -> datetime | None:
    """MIN_AGE_DAYS -> the newest moment an adopted commit or release may be from.

    A value that is not a non-negative number stops the run. The Node version read
    it with Number(), so "3d" became NaN and silently meant "no delay" - the
    opposite of what whoever set the variable asked for.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        days = float(text)
    except ValueError:
        days = math.nan
    if not math.isfinite(days) or days < 0:
        raise ValueError("MIN_AGE_DAYS must be a non-negative number of days, got %r" % raw)
    if days == 0:
        return None
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def iso(when: datetime) -> str:
    """The form GitHub's `until` parameter takes, as Date.toISOString() wrote it."""
    when = when.astimezone(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (when.microsecond // 1000)


def parse_time(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def repo_of(src: dict) -> str | None:
    if src.get("source") == "github":
        return src.get("repo")
    m = GITHUB_REPO.search(src.get("url") or "")
    return m.group(1) if m else None


class Sync:
    """One run: what changed, what could not be checked, and the lookups made."""

    def __init__(self, fetch, token: str = "", cutoff: datetime | None = None):
        self.fetch = fetch
        self.token = token
        self.cutoff = cutoff
        self.changes: list[str] = []
        self.failures: list[str] = []
        self._commits: dict = {}
        self._npm: dict = {}

    def gh(self, path: str) -> object:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return self.fetch("https://api.github.com" + path, headers)

    def latest_commit(self, repo: str, ref: str | None, subpath: str | None) -> str | None:
        key = (repo, ref or "", subpath or "")
        if key not in self._commits:
            query = {"per_page": "1"}
            if ref:
                query["sha"] = ref
            if subpath:
                query["path"] = subpath
            if self.cutoff:
                query["until"] = iso(self.cutoff)
            listing = self.gh("/repos/%s/commits?%s" % (repo, urlencode(query)))
            first = listing[0] if isinstance(listing, list) and listing else None
            self._commits[key] = first.get("sha") if isinstance(first, dict) else None
        return self._commits[key]

    def contains(self, repo: str, base: str, head: str) -> bool:
        """True when `head` already contains `base` (head is the same commit or newer)."""
        c = self.gh("/repos/%s/compare/%s...%s" % (repo, base, head))
        return isinstance(c, dict) and c.get("status") in ("identical", "ahead")

    def sync_source(self, name: str, src: object) -> None:
        if not isinstance(src, dict) or not src.get("sha"):
            return
        repo = repo_of(src)
        if not repo:
            return
        subpath = src.get("path") if src.get("source") == "git-subdir" else None
        nxt = self.latest_commit(repo, src.get("ref"), subpath)
        if not nxt or nxt == src["sha"]:
            return
        # The pin may already be newer than the latest commit touching `path`
        # (or newer than the MIN_AGE_DAYS cutoff); keep it in that case.
        if self.contains(repo, nxt, src["sha"]):
            return
        where = repo + ("/" + subpath if subpath else "")
        self.changes.append("%s: %s %s -> %s" % (name, where, src["sha"][:7], nxt[:7]))
        src["sha"] = nxt

    def latest_npm(self, pkg: str) -> str | None:
        if pkg not in self._npm:
            meta = self.fetch("https://registry.npmjs.org/" + pkg.replace("/", "%2f", 1), {})
            meta = meta if isinstance(meta, dict) else {}
            if self.cutoff is None:
                tags = meta.get("dist-tags")
                found = tags.get("latest") if isinstance(tags, dict) else None
            else:
                times = meta.get("time")
                stable = []
                for version, stamp in (times.items() if isinstance(times, dict) else ()):
                    when = parse_time(stamp)
                    if STABLE.fullmatch(version) and when is not None and when <= self.cutoff:
                        stable.append((when, version))
                stable.sort(key=lambda pair: pair[0])
                found = stable[-1][1] if stable else None
            self._npm[pkg] = found or None
        return self._npm[pkg]

    def sync_mcp_servers(self, label: str, servers: object) -> None:
        if not isinstance(servers, dict):
            return
        for srv, cfg in servers.items():
            args = cfg.get("args") if isinstance(cfg, dict) else None
            if not isinstance(args, list):
                continue
            for i, arg in enumerate(args):
                m = PINNED.fullmatch(arg) if isinstance(arg, str) else None
                if not m:
                    continue
                pkg, cur = m.group(1), m.group(2)
                nxt = self.latest_npm(pkg)
                if not nxt or nxt == cur:
                    continue
                self.changes.append("%s (%s): %s %s -> %s" % (label, srv, pkg, cur, nxt))
                args[i] = "%s@%s" % (pkg, nxt)

    def guarded(self, label: str, step) -> None:
        """A failed lookup leaves that pin unchanged and is reported, not fatal."""
        try:
            step()
        except Exception as e:  # noqa: BLE001 - network, HTTP and payload errors alike
            self.failures.append("%s: %s" % (label, e))


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: object) -> None:
    # newline="" keeps LF on Windows; the format matches JSON.stringify(data, null, 2),
    # so a bump changes only the pinned lines.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main(argv=None, env=None, root: Path = ROOT, fetch=http_get_json) -> int:
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    dry = "--dry-run" in argv
    try:
        cutoff = cutoff_from(env.get("MIN_AGE_DAYS"))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    sync = Sync(fetch, env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or "", cutoff)

    market_file = root / ".claude-plugin" / "marketplace.json"
    market = read_json(market_file)
    plugins = market.get("plugins") or []
    for p in plugins:
        def step(p=p):
            sync.sync_source(p.get("name"), p.get("source"))
            sync.sync_mcp_servers(p.get("name"), p.get("mcpServers"))
        sync.guarded(p.get("name"), step)

    local_mcp = []
    plugins_dir = root / "plugins"
    if plugins_dir.is_dir():
        for d in sorted(plugins_dir.iterdir()):
            file = d / ".mcp.json"
            if not file.is_file():
                continue
            data = read_json(file)
            before = json.dumps(data)
            label = "plugins/" + d.name
            listed = data.get("mcpServers") if isinstance(data, dict) else None
            servers = listed if listed is not None else data
            sync.guarded(label, lambda label=label, servers=servers: sync.sync_mcp_servers(label, servers))
            if json.dumps(data) != before:
                local_mcp.append((file, data))

    print("\n".join(sync.changes) if sync.changes else "All pins are up to date.")
    if sync.failures:
        print("Could not check:\n" + "\n".join(sync.failures), file=sys.stderr)

    if not dry and sync.changes:
        write_json(market_file, market)
        for file, data in local_mcp:
            write_json(file, data)
    if env.get("GITHUB_OUTPUT"):
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="") as fh:
            fh.write("changed=%s\n" % ("true" if sync.changes else "false"))
    # A failed lookup leaves that pin unchanged; fail the run only when nothing could be checked.
    return 1 if sync.failures and len(sync.failures) == len(plugins) else 0


if __name__ == "__main__":
    if not _runtime.meets():
        sys.stderr.write(_runtime.running_shortfall_message() + chr(10))
        sys.exit(1)
    sys.exit(main())
