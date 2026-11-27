"""Count how often the user had to ask what a reply meant.

Reads this machine's Claude Code session transcripts
($CLAUDE_CONFIG_DIR/projects/*/*.jsonl, default ~/.claude/projects) and counts, per
day, the messages the user typed that ask what something means or say a reply was
not understood. It measures the reporting rules in settings/CLAUDE.kibeen.md: run it
before a change and again a week after, on each machine, and compare the rate. The
trend is the measure; a single count is noisy.

Two kinds are counted, each message at most once:
  confused  the message says a reply was not understood ("이해가 안", "뭔말인지")
  asks      the message asks what a term is ("X가 뭐야", "무슨 뜻"). Noisier:
            "다음 작업은 뭐야?" matches too.

Only text the user typed is read. Tool results, command and hook output (text that
starts with "<"), subagent turns, meta messages and messages longer than --max-chars
(usually pasted documents) are skipped. A message copied into a resumed session's
transcript is counted once.

Run: python scripts/count_clarifications.py [--days 30] [--show] [--json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

CONFUSED = re.compile(
    r"이해가\s*안|이해\s*못|뭔\s*말인지|무슨\s*말인지|모르겠|알아\s*들|어렵게\s*말|생소"
)
ASKS = re.compile(
    r"뭐야|뭔데|뭐예요|뭔가요|무슨\s*뜻|무슨\s*말이|뜻이\s*뭐|의미가\s*뭐|의미하는\s*바"
    r"|what does .{1,60} mean",
    re.IGNORECASE,
)


def projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")
    return Path(base) / "projects"


def typed_text(record: dict) -> str | None:
    """The text the user typed in this transcript record, or None if it is not one."""
    if record.get("type") != "user" or record.get("isSidechain") or record.get("isMeta"):
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        content = "\n".join(parts)
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text or text.startswith("<"):
        return None
    return text


def classify(text: str) -> str | None:
    if CONFUSED.search(text):
        return "confused"
    if ASKS.search(text):
        return "asks"
    return None


def local_day(stamp: str) -> datetime.date | None:
    try:
        moment = datetime.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone().date()


def scan(root: Path, since: datetime.date, max_chars: int) -> tuple[dict, list]:
    """Per-day counts and the matching messages, for days on or after `since`."""
    days: dict = {}
    matches: list = []
    seen: set = set()
    for path in sorted(root.glob("*/*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"user"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            text = typed_text(record)
            day = local_day(record.get("timestamp"))
            if text is None or day is None or day < since or len(text) > max_chars:
                continue
            key = record.get("uuid") or (record.get("timestamp"), text)
            if key in seen:
                continue
            seen.add(key)
            row = days.setdefault(day.isoformat(), {"messages": 0, "confused": 0, "asks": 0})
            row["messages"] += 1
            kind = classify(text)
            if kind:
                row[kind] += 1
                matches.append({"day": day.isoformat(), "kind": kind, "text": text})
    return dict(sorted(days.items())), matches


def render(days: dict) -> str:
    out = ["day         messages  confused  asks  rate"]
    total = {"messages": 0, "confused": 0, "asks": 0}
    for day, row in days.items():
        for k in total:
            total[k] += row[k]
        out.append(_row(day, row))
    out.append(_row("total", total))
    return "\n".join(out)


def _row(label: str, row: dict) -> str:
    hits = row["confused"] + row["asks"]
    rate = "%.1f%%" % (100.0 * hits / row["messages"]) if row["messages"] else "-"
    return "%-10s  %8d  %8d  %4d  %s" % (label, row["messages"], row["confused"], row["asks"], rate)


def main(argv: list | None = None, today: datetime.date | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--days", type=int, default=30, help="look back this many days (default 30)")
    ap.add_argument("--projects", type=Path, default=None, help="transcript directory")
    ap.add_argument("--max-chars", type=int, default=500, help="skip longer messages (default 500)")
    ap.add_argument("--show", action="store_true", help="also print the matching messages")
    ap.add_argument("--json", action="store_true", help="print JSON, for summing machines")
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("--days must be 1 or more")
    since = (today or datetime.date.today()) - datetime.timedelta(days=args.days - 1)
    days, matches = scan(args.projects or projects_dir(), since, args.max_chars)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.json:
        payload = {"since": since.isoformat(), "days": days}
        if args.show:
            payload["matches"] = matches
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(render(days))
    if args.show:
        for m in matches:
            print("%s  %-8s  %s" % (m["day"], m["kind"], m["text"].replace("\n", " ")[:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
