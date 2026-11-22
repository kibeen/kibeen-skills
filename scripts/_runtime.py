"""The Python floor, and how to meet it.

Single source of truth for the minimum version. The port shipped a floor of
"3.9+" that nothing ever ran, and the defect hiding behind it (a 3.10+ API)
only surfaced in review - so the number lives here once, every other mention
is checked against it by tests, and the hook refuses to guess.

Deliberately written for very old Python: no f-strings, no annotations, no
`from __future__`. A guard that cannot be parsed by the interpreter it is
meant to reject is not a guard.
"""
import os
import subprocess
import sys

MIN_PYTHON = (3, 11)

# Interpreters to try when the one running us is too old, best first.
# "py -3" is the Windows launcher, which knows about installs not on PATH.
_CANDIDATES = (
    ["python3.14"], ["python3.13"], ["python3.12"], ["python3.11"],
    ["python3"], ["python"], ["py", "-3"],
)

_PROBE = "import sys;sys.stdout.write('%d.%d' % sys.version_info[:2])"


def floor_str():
    return "%d.%d" % MIN_PYTHON


def version_str(info=None):
    return "%d.%d" % (info or sys.version_info)[:2]


def meets(info=None):
    return tuple((info or sys.version_info)[:2]) >= MIN_PYTHON


def _probe(argv):
    """Version of the interpreter `argv` starts, or None if it will not run."""
    try:
        r = subprocess.run(
            argv + ["-c", _PROBE],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
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


def find_interpreter():
    """An interpreter that meets the floor, as an argv list, or None.

    Prefers the one already running, so a satisfied machine spawns nothing.
    """
    if meets():
        return [sys.executable]
    seen = set()
    for argv in _CANDIDATES:
        key = tuple(argv)
        if key in seen:
            continue
        seen.add(key)
        info = _probe(argv)
        if info is not None and meets(info):
            return argv
    return None


def upgrade_hint():
    """One command the user can run to get a new-enough Python."""
    want = floor_str()
    if sys.platform == "win32":
        return "winget install Python.Python.3.13"
    if sys.platform == "darwin":
        return "brew install python@3.13"
    for mgr, cmd in (
        ("apt-get", "sudo apt install python" + want),
        ("dnf", "sudo dnf install python" + want.replace(".", "")),
        ("pacman", "sudo pacman -S python"),
        ("zypper", "sudo zypper install python3"),
    ):
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if d and os.path.exists(os.path.join(d, mgr)):
                return cmd
    return "install Python " + want + " or newer"


def shortfall_message():
    """What to tell the user when no interpreter on this machine is new enough."""
    return (
        "kibeen-skills 설정 동기화를 건너뜁니다: Python "
        + floor_str() + " 이상이 필요하지만 이 머신에서 찾은 것은 "
        + version_str() + " 입니다. 설치 후 자동 복구됩니다 — " + upgrade_hint()
    )
