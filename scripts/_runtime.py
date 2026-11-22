"""The Python floor, and how to meet it.

Single source of truth for the minimum version. The port shipped a floor of
"3.9+" that nothing ever ran, and the defect hiding behind it (a 3.10+ API)
only surfaced in review - so the number lives here once, every other mention
is checked against it by tests, and nothing re-hardcodes a version.

Deliberately written without f-strings, annotations or `from __future__`: a
guard the rejected interpreter cannot parse never runs. In practice its
callers use `from __future__ import annotations`, so 3.7 is the oldest
interpreter that reaches this check at all.
"""
import os
import subprocess
import sys

MIN_PYTHON = (3, 11)

# One probe must not eat the hook's budget: the caller also runs the sync
# itself. 7 candidates x PROBE_TIMEOUT_S has to leave room under the 120s
# SessionStart timeout.
PROBE_TIMEOUT_S = 3
_LOOKAHEAD = 3  # how many minor versions above the floor to look for

_PROBE = "import sys;sys.stdout.write('%d.%d' % sys.version_info[:2])"


def floor_str():
    return "%d.%d" % MIN_PYTHON


def version_str(info=None):
    return "%d.%d" % tuple((info or sys.version_info)[:2])


def meets(info=None):
    return tuple((info or sys.version_info)[:2]) >= MIN_PYTHON


def candidates():
    """Interpreters to try, newest first, derived from the floor.

    `py -3` is the Windows launcher, which knows about installs not on PATH.
    """
    major, minor = MIN_PYTHON
    out = []
    for m in range(minor + _LOOKAHEAD, minor - 1, -1):
        out.append(["python%d.%d" % (major, m)])
    out.append(["python%d" % major])
    out.append(["python"])
    out.append(["py", "-%d" % major])
    return out


def _probe(argv):
    """Version of the interpreter `argv` starts, or None if it will not run."""
    try:
        r = subprocess.run(
            argv + ["-c", _PROBE],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        parts = r.stdout.decode("ascii", "replace").strip().split(".")
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def survey():
    """(argv, version) of an interpreter meeting the floor, else (None, best).

    `best` is the newest version found anywhere, so the caller can report what
    the machine actually has instead of whatever happens to be running.
    Prefers the running interpreter when it qualifies, so a healthy machine
    spawns nothing.
    """
    if meets():
        return [sys.executable], tuple(sys.version_info[:2])
    best = tuple(sys.version_info[:2])
    for argv in candidates():
        info = _probe(argv)
        if info is None:
            continue
        if meets(info):
            return argv, info
        if info > best:
            best = info
    return None, best


def find_interpreter():
    return survey()[0]


def upgrade_hint():
    """One command that gets a Python meeting the floor. Version comes from
    MIN_PYTHON, never a second hardcoded number."""
    want = floor_str()
    if sys.platform == "win32":
        return "winget install Python.Python." + want
    if sys.platform == "darwin":
        return "brew install python@" + want
    for mgr, cmd in (
        ("apt-get", "sudo apt install python" + want),
        ("dnf", "sudo dnf install python" + want),
        ("pacman", "sudo pacman -S python"),
        ("zypper", "sudo zypper install python" + want.replace(".", "")),
    ):
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if d and os.path.exists(os.path.join(d, mgr)):
                return cmd
    return "install Python " + want + " or newer"


def shortfall_message(found=None):
    """What to tell the user when nothing on this machine is new enough."""
    return (
        "kibeen-skills 설정 동기화를 건너뜁니다: Python "
        + floor_str() + " 이상이 필요하지만 이 머신에서 가장 새 것은 "
        + version_str(found) + " 입니다. 설치하면 다음 세션에 자동 복구됩니다 — "
        + upgrade_hint()
    )


def running_shortfall_message():
    """For a direct run: the interpreter the user invoked is the one at fault,
    so do not claim anything about the rest of the machine."""
    return (
        "Python " + floor_str() + " 이상이 필요하지만 이 인터프리터는 "
        + version_str() + " 입니다 — " + upgrade_hint()
    )
