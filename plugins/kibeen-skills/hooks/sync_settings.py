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
    for name in ("settings.json", "settings.local.json"):
        try:
            s = json.loads((Path(d) / ".claude" / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # missing or unreadable settings file
        if (s.get("enabledPlugins") or {}).get("kibeen-skills@kibeen-skills"):
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

CHILD_TIMEOUT_S = 90  # leaves room under the 120s SessionStart hook timeout
error_log = data_dir / "last-error.log"


def note(text: str) -> None:
    """Tell the user, through the one channel a SessionStart hook has."""
    sys.stdout.write(json.dumps({"systemMessage": text}) + chr(10))


def read_stamp() -> dict:
    try:
        return json.loads(stamp_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def note_throttled(last: dict, text: str) -> None:
    """Notify at most once per INTERVAL_S.

    Retrying and notifying are throttled separately: a broken sync should be
    retried every session so a fix takes effect at once, while the message
    about it should not repeat all day.
    """
    if time.time() - (last.get("notified_at") or 0) < INTERVAL_S:
        return
    note(text)


def write_stamp(sha, scope: str, status, mode: str, throttle_from: dict | None = None) -> None:
    """Record the run. `sha` None means "do not suppress the next attempt"."""
    record = {
        "at": time.time(),
        "sha": sha,
        "scope": scope,
        "status": status,
        "mode": mode,
    }
    if throttle_from is not None:
        prev = throttle_from.get("notified_at") or 0
        record["notified_at"] = (
            prev if time.time() - prev < INTERVAL_S else time.time()
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    stamp_file.write_text(json.dumps(record) + chr(10), encoding="utf-8")


def record_error(detail: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    error_log.write_text(
        time.strftime("%Y-%m-%d %H:%M:%S") + chr(10) + detail, encoding="utf-8"
    )


def marketplace_root() -> Path | None:
    local = config_dir / "plugins" / "marketplaces" / "kibeen-skills"
    if (local / SCRIPT_REL).exists():
        return local
    # Fall back to asking the CLI where the marketplace lives (e.g. a local-directory marketplace).
    try:
        ls = subprocess.run(
            ["claude", "plugin", "marketplace", "list", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
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

    argv, found = _runtime.survey()
    if argv is None:
        # Nothing here can run the sync. Say so - at most once a day - and do
        # NOT record the sha: the next session must try again, or installing
        # Python would not recover for 24h even though we just promised it.
        note_throttled(last, _runtime.shortfall_message(found))
        write_stamp(None, scope, None, "python-too-old", throttle_from=last)
        sys.exit(0)

    args = argv + [
        str(root / SCRIPT_REL),
        "--hook",
        *([] if auto_apply else ["--check"]),
        *(["--scope", "project", "--project-dir", project_dir] if scope == "project" else []),
    ]
    out, err, status = "", "", None
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=CHILD_TIMEOUT_S,
        )
        out, err, status = r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        # Stamp a timeout too (status null, as the old spawnSync reported it);
        # skipping the stamp would retry this long run on every single session.
        pass

    # The sync's own failures happen in that child, which is where every defect
    # found in review lived. Reporting only exceptions raised *here* is what let
    # them ship: the child exited non-zero, its traceback went to a stderr we
    # discarded, and the stamp then suppressed retries for a day.
    # 0 = applied, 2 = --check found differences. Anything else is a failure.
    if status is not None and status not in (0, 2):
        record_error(
            "apply_settings.py exited " + str(status) + chr(10)
            + "--- stderr ---" + chr(10) + err.strip() + chr(10)
            + "--- stdout ---" + chr(10) + out.strip() + chr(10)
        )
        note_throttled(
            last,
            "kibeen-skills 설정 동기화가 실패했습니다 (세션은 그대로 진행됩니다). "
            "원인: " + str(error_log),
        )
        # No sha: retry next session, so a fixed cause recovers immediately.
        write_stamp(None, scope, status, "failed", throttle_from=last)
        sys.exit(0)

    write_stamp(sha, scope, status, "apply" if auto_apply else "check")
    if out.strip().startswith("{"):
        sys.stdout.write(out)
except Exception:
    # A failed sync must never block a session - but it must not look healthy
    # either. Swallowing the traceback is what let four defects ship.
    try:
        record_error(traceback.format_exc())
        note_throttled(
            last,
            "kibeen-skills 설정 동기화가 오류로 중단됐습니다 (세션은 그대로 진행됩니다). "
            "원인: " + str(error_log),
        )
        write_stamp(None, scope, None, "crashed", throttle_from=last)
    except Exception:
        pass

sys.exit(0)
