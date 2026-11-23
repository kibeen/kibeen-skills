#!/usr/bin/env python3
"""Bring this machine's Claude Code user settings in line with settings/claude-settings.json
(~/.claude/settings.json, or $CLAUDE_CONFIG_DIR/settings.json).

1. Clean up (uses the `claude` CLI):
   - removes the marketplaces listed in `retired.marketplaces` (this also uninstalls their plugins),
   - uninstalls the plugins listed in `retired.plugins`,
   - uninstalls kibeen-skills plugins that are no longer in .claude-plugin/marketplace.json.
2. Merge:
   - extraKnownMarketplaces: entries from the repo file replace same-named entries.
   - enabledPlugins: adds the repo's plugins; a plugin this machine set to false stays false.
     Entries for kibeen-skills plugins that left the catalog are dropped.
   - outputStyle: set to the repo's style, also replacing a style chosen on this machine;
     KIBEEN_KEEP_OUTPUT_STYLE=1 keeps that choice. Project scope only fills a missing style.
   - Every other key in settings.json is left as is. A timestamped backup is written first.
3. CLAUDE.md: keeps settings/CLAUDE.kibeen.md as a marked block in the user's CLAUDE.md
   (other content untouched, backup first).

Usage: python scripts/apply_settings.py [--scope user|project] [--project-dir DIR]
                                        [--dry-run | --check] [--hook] [--marketplaces-only]
  --scope project      apply to one project instead of the user: <DIR>/.claude/settings.json and
                       <DIR>/.claude/CLAUDE.md; marketplaces and plugins are added/installed with
                       --scope project (project-enabled plugins are not fetched on startup).
                       DIR defaults to $CLAUDE_PROJECT_DIR, then the current directory.
  --dry-run            print every step, change nothing
  --check              print only what differs, change nothing; exit 2 when something differs
  --hook               print only a Claude Code hook JSON {"systemMessage": ...} (or nothing when in sync)
  --marketplaces-only  skip enabling plugins and the output style (clean-up and marketplace
                       declarations still run)

Standard library only, no Node.js. The minimum Python version is declared
once in scripts/_runtime.py and checked at startup.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# The hook's parent reads this process' stdout as UTF-8, and the Korean text below
# would otherwise be written in the console code page (cp949/cp1252): mojibake on
# decode, or UnicodeEncodeError when the page cannot represent it. Node was always
# UTF-8 here, so pin it. hook_message() additionally escapes to ASCII.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass

# The floor is declared once, in scripts/_runtime.py. Check it before any work:
# this script shipped a floor it had never been run on, and the 3.10+ API behind
# that claim only turned up in review.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _runtime  # noqa: E402

if not _runtime.meets():
    sys.stderr.write(_runtime.running_shortfall_message() + chr(10))
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SELF = ROOT / "scripts" / "apply_settings.py"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


fragment = read_json(ROOT / "settings" / "claude-settings.json")
catalog = read_json(ROOT / ".claude-plugin" / "marketplace.json")


def arg_val(name: str) -> str | None:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i > 0 and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


SCOPE = arg_val("--scope") or "user"
if SCOPE not in ("user", "project"):
    print("--scope must be user or project", file=sys.stderr)
    sys.exit(1)

PROJECT_DIR = Path(
    arg_val("--project-dir") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
).resolve()
config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
dir_ = (PROJECT_DIR / ".claude") if SCOPE == "project" else config_dir
file_ = dir_ / "settings.json"
scope_args = ["--scope", SCOPE]

CHECK = "--check" in sys.argv
HOOK = "--hook" in sys.argv
DRY = CHECK or "--dry-run" in sys.argv
MARKETS_ONLY = "--marketplaces-only" in sys.argv
KEEP_STYLE = os.environ.get("KIBEEN_KEEP_OUTPUT_STYLE") == "1"


def log(*parts: object) -> None:
    if not HOOK:
        print(*parts)


def same_path(a, b) -> bool:
    try:
        pa, pb = Path(a or "").resolve(), Path(b or "").resolve()
    except (OSError, ValueError):
        return False
    if sys.platform == "win32":
        return str(pa).lower() == str(pb).lower()
    return pa == pb


def in_scope(p: dict) -> bool:
    if (p.get("scope") or "user") != SCOPE:
        return False
    return SCOPE != "project" or same_path(p.get("projectPath"), PROJECT_DIR)


def source_arg(src: dict | None) -> str | None:
    if not src:
        return None
    if src.get("source") == "github":
        return src.get("repo")
    if src.get("source") in ("git", "url"):
        return src.get("url")
    return None


def read_settings() -> dict:
    """Parse settings.json, or stop.

    Returning {} for an unparseable file would make the merge below write a file
    holding only this repo's keys, silently dropping everything the machine had
    (the old JS threw instead). utf-8-sig tolerates the BOM that Notepad and
    PowerShell 5.1 add.
    """
    if not file_.exists():
        return {}
    try:
        return json.loads(file_.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        fail(
            f"{file_} is not valid JSON ({e}); refusing to overwrite it. "
            "Fix or move the file, then run this again."
        )


diffs: list[str] = []  # human-readable list of what differs from the repo
failures = 0
backup_path = ""
_backed_up = False


def stamp() -> str:
    # Matches the old JS format: new Date().toISOString() with : and . replaced by -
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond // 1000:03d}Z"


def backup_once() -> None:
    global _backed_up, backup_path
    if _backed_up or not file_.exists():
        return
    backup_path = f"{file_}.bak-{stamp()}"
    shutil.copy2(file_, backup_path)
    _backed_up = True
    log(f"Backup: {backup_path}")


def claude(args: list[str]) -> tuple[bool, str]:
    """Run the `claude` CLI. On Windows it may be installed as claude.cmd, which
    only runs through the shell, so fall back to a shell invocation."""
    try:
        r = subprocess.run(
            ["claude", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        if sys.platform != "win32":
            return False, ""
        cmd = " ".join(
            a if re.fullmatch(r"[\w@./:-]+", a) else f'"{a}"' for a in ["claude", *args]
        )
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
        except OSError:
            return False, ""
    except OSError:
        return False, ""
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def claude_json(args: list[str]):
    ok, out = claude(args)
    if not ok:
        return None
    i = out.find("[")
    if i < 0:
        return None
    try:
        return json.loads(out[i:])
    except json.JSONDecodeError:
        return None


def summary() -> str:
    def count(pattern: str) -> int:
        return sum(1 for d in diffs if re.match(pattern, d))

    pairs = [
        (count(r"^install "), "설치"),
        (count(r"^(remove marketplace|uninstall)"), "정리"),
        (count(r"^(marketplace |add marketplace)"), "마켓플레이스 선언"),
        (count(r"^plugin .*: (enabled|removed)"), "플러그인 켜기·끄기"),
        (count(r"^outputStyle: "), "출력 스타일"),
        (count(r"^CLAUDE\.md "), "지침"),
    ]
    return ", ".join(f"{label} {n}건" for n, label in pairs if n)


def style_notice() -> str:
    """The replaced style and the way to keep it, for the hook message.

    The hook is how this change reaches every machine, and its message is all
    the user sees of a run, so a count alone would hide what was overwritten.
    """
    if not style_override:
        return ""
    have, want = style_override
    return (
        f" 출력 스타일 {have} → {want}"
        " (이 머신의 스타일을 유지하려면 환경변수 KIBEEN_KEEP_OUTPUT_STYLE=1)."
    )


def fail(message: str) -> None:
    """Stop with a reason the user actually sees.

    Under --hook stderr goes nowhere (the parent swallows it), so without a
    hook message the run would stall silently and the daily back-off would
    repeat it unexplained every day.
    """
    print(message, file=sys.stderr)
    if HOOK:
        hook_message("kibeen-skills 설정 동기화 중단: " + message)
    sys.exit(1)


def hook_message(text: str) -> None:
    # ensure_ascii keeps the payload pure ASCII, so it survives any stdout
    # encoding; the parent JSON-parses it back into the Korean text.
    sys.stdout.write(json.dumps({"systemMessage": text}) + "\n")


# ---- 1. clean-up ---------------------------------------------------------
retired = fragment.get("retired") or {}
in_catalog = {f"{p['name']}@{catalog['name']}" for p in catalog["plugins"]}


def left_catalog(plugin_id: str) -> bool:
    return plugin_id.endswith(f"@{catalog['name']}") and plugin_id not in in_catalog


installed = claude_json(["plugin", "list", "--json"])
known = claude_json(["plugin", "marketplace", "list", "--json"])
plan: list[dict] = []

if installed is None or known is None:
    log("claude CLI not available: skipping clean-up of retired marketplaces and plugins.")
else:
    declared = read_settings().get("extraKnownMarketplaces") or {}
    known_names = {m["name"] for m in known}
    # A project only owns the marketplaces its own settings declare.
    owned_names = set(declared) if SCOPE == "project" else (known_names | set(declared))
    for m in retired.get("marketplaces") or []:
        if m in owned_names:
            plan.append({
                "what": f"remove marketplace {m}",
                "args": ["plugin", "marketplace", "remove", m, *scope_args],
            })
    gone_markets = {p["args"][3] for p in plan}
    retired_plugins = set(retired.get("plugins") or [])
    mine = [p for p in installed if in_scope(p)]
    installed_ids = {p["id"] for p in mine}
    # Renamed plugins: install the new id before the old one is removed below.
    for old_id, new_id in (fragment.get("renamed") or {}).items():
        if old_id in installed_ids and new_id not in installed_ids:
            plan.append({
                "what": f"install {new_id} (renamed from {old_id})",
                "args": ["plugin", "install", new_id, *scope_args],
            })
    for p in mine:
        plugin_id = p["id"]
        if plugin_id.split("@")[-1] in gone_markets:
            continue  # removed with its marketplace
        if plugin_id in retired_plugins:
            plan.append({
                "what": f"uninstall {plugin_id} (retired)",
                "args": ["plugin", "uninstall", plugin_id, *scope_args],
            })
        elif left_catalog(plugin_id):
            plan.append({
                "what": f"uninstall {plugin_id} (no longer in {catalog['name']})",
                "args": ["plugin", "uninstall", plugin_id, *scope_args],
            })
    if SCOPE == "project":
        # Project settings are not fetched on startup, so add and install explicitly.
        for name, entry in (fragment.get("extraKnownMarketplaces") or {}).items():
            src = source_arg(entry.get("source"))
            if name not in known_names and src:
                plan.append({
                    "what": f"add marketplace {name}",
                    "args": ["plugin", "marketplace", "add", src, *scope_args],
                })
        if not MARKETS_ONLY:
            local_off = read_settings().get("enabledPlugins") or {}
            for plugin_id, on in (fragment.get("enabledPlugins") or {}).items():
                if on and local_off.get(plugin_id) is not False and plugin_id not in installed_ids:
                    plan.append({
                        "what": f"install {plugin_id}",
                        "args": ["plugin", "install", plugin_id, *scope_args],
                    })

for step in plan:
    diffs.append(step["what"])
    if DRY:
        if not CHECK:
            log(f"would {step['what']}")
        continue
    backup_once()
    ok, out = claude(step["args"])
    if not ok:
        failures += 1
    tail = "" if ok else "\n  " + (out.strip().split("\n")[-1] if out.strip() else "")
    log(f"{'done' if ok else 'FAILED'}: {step['what']}{tail}")

# ---- 2. merge ------------------------------------------------------------
current = read_settings()  # re-read: the CLI above edits settings.json
next_ = copy.deepcopy(current)
report: list[str] = []
notes: list[str] = []

next_["extraKnownMarketplaces"] = dict(current.get("extraKnownMarketplaces") or {})
for name, entry in (fragment.get("extraKnownMarketplaces") or {}).items():
    if (current.get("extraKnownMarketplaces") or {}).get(name) == entry:
        continue
    existed = name in (current.get("extraKnownMarketplaces") or {})
    next_["extraKnownMarketplaces"][name] = entry
    report.append(f"marketplace {name}: {'updated' if existed else 'added'}")
for m in retired.get("marketplaces") or []:
    if m not in next_["extraKnownMarketplaces"]:
        continue
    del next_["extraKnownMarketplaces"][m]
    report.append(f"marketplace {m}: declaration removed")

next_["enabledPlugins"] = dict(current.get("enabledPlugins") or {})
stale = list(retired.get("plugins") or []) + [
    pid for pid in next_["enabledPlugins"] if left_catalog(pid)
]
for plugin_id in stale:
    if plugin_id not in next_["enabledPlugins"]:
        continue
    del next_["enabledPlugins"][plugin_id]
    report.append(f"plugin {plugin_id}: removed from enabledPlugins")

if not MARKETS_ONLY:
    for plugin_id, on in (fragment.get("enabledPlugins") or {}).items():
        if (current.get("enabledPlugins") or {}).get(plugin_id) is False:
            notes.append(f"plugin {plugin_id}: kept disabled on this machine")
            continue
        if (current.get("enabledPlugins") or {}).get(plugin_id) == on:
            continue
        next_["enabledPlugins"][plugin_id] = on
        report.append(f"plugin {plugin_id}: enabled")

# The repo's style is the default on every machine, also over a style set there
# before. KIBEEN_KEEP_OUTPUT_STYLE=1 keeps a machine's own choice instead. A
# project's settings are committed and shared, so project scope only fills a
# missing style and never replaces one the team chose.
style_override = None  # (old, new) when a style set on this machine is replaced
if not MARKETS_ONLY and fragment.get("outputStyle"):
    want = fragment["outputStyle"]
    have = current.get("outputStyle")
    had = "outputStyle" in current
    if have == want:
        pass
    elif had and KEEP_STYLE:
        notes.append(f"outputStyle: kept {have} chosen on this machine (KIBEEN_KEEP_OUTPUT_STYLE=1)")
    elif had and SCOPE == "project":
        notes.append(f"outputStyle: kept {have} set in the project settings")
    else:
        next_["outputStyle"] = want
        if had:
            style_override = (have, want)
            report.append(
                f"outputStyle: set to {want} (was {have}; KIBEEN_KEEP_OUTPUT_STYLE=1 keeps it)"
            )
        else:
            report.append(f"outputStyle: set to {want}")

diffs.extend(report)

# ---- 3. CLAUDE.md instruction block ---------------------------------------
# settings/CLAUDE.kibeen.md is kept as a managed block in the user's CLAUDE.md;
# everything outside the markers is left untouched. No repo file -> block removed.
memo_src = ROOT / "settings" / "CLAUDE.kibeen.md"
memo_file = dir_ / "CLAUDE.md"
BEGIN = (
    "<!-- BEGIN kibeen-skills: managed by apply_settings.py, "
    "edit settings/CLAUDE.kibeen.md in the repo -->"
)
END = "<!-- END kibeen-skills -->"
BLOCK_RE = re.compile(
    r"<!-- BEGIN kibeen-skills[^\n]*-->\n.*?<!-- END kibeen-skills -->\n?", re.DOTALL
)

if memo_file.exists():
    try:
        memo_now = memo_file.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as e:
        fail(f"{memo_file} is not UTF-8 ({e}); fix or move the file, then run this again.")
else:
    memo_now = ""
wanted = (
    f"{BEGIN}\n{memo_src.read_text(encoding='utf-8').replace(chr(13) + chr(10), chr(10)).strip()}\n{END}\n"
    if memo_src.exists()
    else ""
)
has_block = bool(BLOCK_RE.search(memo_now))
if has_block:
    memo_next = BLOCK_RE.sub(lambda _: wanted, memo_now, count=1)
elif wanted:
    if not memo_now:
        sep = ""
    elif memo_now.endswith("\n\n"):
        sep = ""
    elif memo_now.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    memo_next = memo_now + sep + wanted
else:
    memo_next = memo_now

if memo_next != memo_now:
    what = "removed" if not wanted else ("updated" if has_block else "added")
    diffs.append(f"CLAUDE.md instructions: {what}")
    if not DRY:
        if memo_file.exists():
            shutil.copy2(memo_file, f"{memo_file}.bak-{stamp()}")
        dir_.mkdir(parents=True, exist_ok=True)
        # newline="" keeps the bytes as-is; text mode would rewrite the whole
        # file to CRLF on Windows, user content outside our markers included.
        # newline="" keeps the bytes as-is; text mode would rewrite the file to
        # CRLF on Windows. open() has taken newline since forever, while
        # Path.write_text only got it in 3.10 - keep open() so the floor
        # stays wherever the declared minimum goes.
        with open(memo_file, "w", encoding="utf-8", newline="") as fh:
            fh.write(memo_next)
        log(f"CLAUDE.md instructions {what}: {memo_file}")
    elif not CHECK:
        verb = {"removed": "remove", "added": "add"}.get(what, "update")
        log(f"would {verb} the kibeen-skills block in {memo_file}")

if CHECK:
    if HOOK:
        if diffs:
            extra = " --scope project" if SCOPE == "project" else ""
            hook_message(
                f"kibeen-skills 설정과 다름 [{SCOPE}] ({summary()}).{style_notice()} "
                f'확인: python "{SELF}"{extra} --dry-run'
            )
    else:
        if diffs:
            print(f"{len(diffs)} item(s) differ:\n" + "\n".join("  " + d for d in diffs))
        else:
            print("In sync.")
    sys.exit(2 if diffs else 0)

log("\n".join([str(file_), *(report or ["Settings already up to date."]), *notes]))
if not DRY and report:
    dir_.mkdir(parents=True, exist_ok=True)
    backup_once()
    with open(file_, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(next_, indent=2, ensure_ascii=False) + "\n")
    log("Written. Restart Claude Code; enabled plugins that are not installed yet are fetched on startup.")

if HOOK and not DRY and diffs:
    hook_message(
        f"kibeen-skills 설정을 자동 적용했습니다 [{SCOPE}] "
        f"({summary()}{f', 실패 {failures}건' if failures else ''}).{style_notice()} "
        f"새로 켠 플러그인은 다음 세션부터 쓸 수 있습니다. "
        f"되돌리기: {backup_path or '백업 없음'}"
    )
