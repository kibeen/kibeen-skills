#!/usr/bin/env python3
"""SessionStart hook: bring this machine in line with the kibeen-skills settings.

Runs when the kibeen-skills checkout has a new commit, or at most once a day otherwise.
It applies every difference (installs, enables, removes) with a settings backup,
and shows the user a one-line systemMessage of what it did. Nothing is added to the
model's context. Set KIBEEN_AUTO_APPLY=0 to only be notified instead.

Standard library only, no Node.js. The minimum Python version is declared
once in scripts/_runtime.py; this hook picks an interpreter that meets it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True  # no __pycache__ in the user checkout
from pathlib import Path

INTERVAL_S = 24 * 60 * 60

config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
data_dir = Path(
    os.environ.get("CLAUDE_PLUGIN_DATA")
    or (config_dir / "plugins" / "data" / "kibeen-skills")
)
auto_apply = os.environ.get("KIBEEN_AUTO_APPLY") != "0"

# Installed with --scope project -> sync that project only; otherwise sync the user settings.
project_dir = os.environ.get("CLAUDE_PROJECT_DIR")


def enabled_in_project(d: str) -> bool:
    """Whether the project at `d` enables this plugin.

    This runs before the guarded block, on a file this repo does not own, so
    nothing in it may raise: a non-UTF-8 file (UnicodeDecodeError is a
    ValueError, not a JSONDecodeError) or a top level that is not an object
    used to abort the hook with a raw traceback - once per interpreter, since
    hooks.json then retries under python3 and py -3 - and left nothing in
    last-error.log.
    """
    for name in ("settings.json", "settings.local.json"):
        try:
            s = json.loads((Path(d) / ".claude" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # missing, unreadable, not UTF-8, or not JSON
        enabled = s.get("enabledPlugins") if isinstance(s, dict) else None
        if isinstance(enabled, dict) and enabled.get("kibeen-skills@kibeen-skills"):
            return True
    return False


scope = "project" if project_dir and enabled_in_project(project_dir) else "user"
if scope == "project":
    stamp_key = hashlib.sha1(
        str(Path(project_dir).resolve()).encode("utf-8")
    ).hexdigest()[:12]
else:
    stamp_key = "user"
stamp_file = data_dir / f"last-sync-{stamp_key}.json"

SCRIPT_REL = Path("scripts") / "apply_settings.py"

HOOK_TIMEOUT_S = 120        # hooks.json; the whole run must fit inside it
CLI_PROBE_TIMEOUT_S = 5     # locating the marketplace through the claude CLI
CHILD_TIMEOUT_S = 90        # the sync itself
# A failed attempt this slow is not retried next session: doing so would add
# its cost to every session start. A fast failure is retried, so fixing its
# cause takes effect at once.
CHEAP_FAILURE_S = 5
error_log = data_dir / "last-error.log"


def note(text: str) -> None:
    """Tell the user, through the one channel a SessionStart hook has."""
    sys.stdout.write(json.dumps({"systemMessage": text}) + chr(10))


def read_stamp() -> dict:
    """The previous run, or {} for anything unreadable.

    This is read before the guarded block, so a corrupt stamp must not be able
    to raise: a non-dict payload used to reach .get() and a non-UTF-8 file used
    to escape as a raw traceback, both aborting the session start.
    """
    try:
        data = json.loads(stamp_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def should_notify(last: dict) -> bool:
    """Retrying and notifying are throttled separately: retry as often as it is
    cheap to, but do not repeat the same message all day."""
    return time.time() - (last.get("notified_at") or 0) >= INTERVAL_S


def write_stamp(sha, scope: str, status, mode: str, last=None, notified=False) -> None:
    """Record the run. `sha` None means "do not suppress the next attempt"."""
    record = {
        "at": time.time(),
        "sha": sha,
        "scope": scope,
        "status": status,
        "mode": mode,
    }
    if last is not None:
        record["notified_at"] = (
            time.time() if notified else (last.get("notified_at") or 0)
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    stamp_file.write_text(json.dumps(record) + chr(10), encoding="utf-8")


def record_error(detail: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    error_log.write_text(
        time.strftime("%Y-%m-%d %H:%M:%S") + chr(10) + detail, encoding="utf-8"
    )


def as_text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw


def marketplace_root() -> Path | None:
    local = config_dir / "plugins" / "marketplaces" / "kibeen-skills"
    if (local / SCRIPT_REL).exists():
        return local
    # Fall back to asking the CLI where the marketplace lives (e.g. a local-directory marketplace).
    try:
        ls = subprocess.run(
            ["claude", "plugin", "marketplace", "list", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CLI_PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = ls.stdout or ""
    i = out.find("[")
    if i < 0:
        return None
    try:
        entries = json.loads(out[i:])
    except json.JSONDecodeError:
        return None
    loc = next(
        (m.get("installLocation") for m in entries if m.get("name") == "kibeen-skills"), None
    )
    if loc and (Path(loc) / SCRIPT_REL).exists():
        return Path(loc)
    return None


def head_sha(root: Path) -> str:
    try:
        head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        loose = root / ".git" / ref
        if loose.exists():
            return loose.read_text(encoding="utf-8").strip()
        packed = (root / ".git" / "packed-refs").read_text(encoding="utf-8")
        for line in packed.split("\n"):
            if line.endswith(" " + ref):
                return line.split(" ")[0]
        return ""
    except OSError:
        return ""


last = read_stamp()

try:
    root = marketplace_root()
    if root is None:
        sys.exit(0)
    sha = head_sha(root)
    if sha and sha == last.get("sha") and time.time() - (last.get("at") or 0) < INTERVAL_S:
        sys.exit(0)

    # Floor and interpreter selection live in the marketplace checkout, so the
    # number is not duplicated here. Import after locating root.
    sys.path.insert(0, str(root / "scripts"))
    import _runtime

    started = time.time()
    argv, found = _runtime.survey()
    if argv is None:
        # Nothing here can run the sync. Say so - at most once a day - and do
        # NOT record the sha: the next session must try again, or installing
        # Python would not recover for 24h even though we just promised it.
        notify = should_notify(last)
        if notify:
            note(_runtime.shortfall_message(found))
        # Probing every candidate is not free either, so the same cost rule
        # applies: back off when the attempt was slow.
        cheap = time.time() - started < CHEAP_FAILURE_S
        write_stamp(None if cheap else sha, scope, None, "python-too-old",
                    last=last, notified=notify)
        sys.exit(0)

    args = argv + [
        "-B",  # no __pycache__ in the user checkout
        str(root / SCRIPT_REL),
        "--hook",
        *([] if auto_apply else ["--check"]),
        *(["--scope", "project", "--project-dir", project_dir] if scope == "project" else []),
    ]
    out, err, status, timed_out = "", "", None, False
    started = time.time()
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=CHILD_TIMEOUT_S,
        )
        out, err, status = r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired as exc:
        # Whatever it managed to say before being killed is the only clue.
        timed_out = True
        out, err = as_text(exc.stdout), as_text(exc.stderr)

    # The sync's own failures happen in that child, which is where every defect
    # found in the port lived. Reporting only exceptions raised *here* is what
    # let them ship: the child exited non-zero, its traceback went to a stderr
    # we discarded, and the stamp then suppressed retries for a day.
    # 0 = applied, 2 = --check found differences. Anything else is a failure,
    # and so is being killed at the timeout - which used to land in the success
    # branch below because its status is None.
    if timed_out or status not in (0, 2):
        record_error(
            ("apply_settings.py timed out after %ds" % CHILD_TIMEOUT_S if timed_out
             else "apply_settings.py exited " + str(status)) + chr(10)
            + "--- stderr ---" + chr(10) + err.strip() + chr(10)
            + "--- stdout ---" + chr(10) + out.strip() + chr(10)
        )
        notify = should_notify(last)
        if notify:
            if out.strip().startswith("{"):
                # The child's own message. apply_settings.fail() writes one to
                # stdout naming what the user has to do ("claude CLI not
                # found", "settings.json is not valid JSON"); replacing it with
                # "see the log" buries the only actionable part.
                sys.stdout.write(out)
            else:
                note(
                    "kibeen-skills 설정 동기화가 "
                    + ("시간 초과로 중단됐습니다" if timed_out else "실패했습니다")
                    + " (세션은 그대로 진행됩니다). 원인: " + str(error_log)
                )
        # Retry only what is cheap to retry. A timeout costs CHILD_TIMEOUT_S
        # and a slow crash nearly as much; repeating either every session would
        # delay every session start, which is what this hook must never do.
        # Anything that failed fast (missing CLI, bad settings.json) is retried,
        # so fixing the cause takes effect on the next session.
        cheap = not timed_out and time.time() - started < CHEAP_FAILURE_S
        write_stamp(
            None if cheap else sha, scope, status,
            "timeout" if timed_out else "failed", last=last, notified=notify,
        )
        sys.exit(0)

    write_stamp(sha, scope, status, "apply" if auto_apply else "check")
    if out.strip().startswith("{"):
        sys.stdout.write(out)
except Exception:
    # A failed sync must never block a session - but it must not look healthy
    # either. Swallowing the traceback is what let four defects ship.
    try:
        record_error(traceback.format_exc())
        notify = should_notify(last)
        if notify:
            note(
                "kibeen-skills 설정 동기화가 오류로 중단됐습니다 "
                "(세션은 그대로 진행됩니다). 원인: " + str(error_log)
            )
        write_stamp(None, scope, None, "crashed", last=last, notified=notify)
    except Exception:
        pass

sys.exit(0)
