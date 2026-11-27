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

Only text the user typed is read. Tool results, text blocks the client or harness
added (they start with "<": the IDE's open-file note, command and hook output),
subagent turns, meta messages, /compact summaries, prompts from automation and
messages longer than --max-chars (usually pasted documents) are skipped. A message
copied into a resumed session's transcript is counted once.

Claude Code deletes transcripts older than `cleanupPeriodDays` (30 by default), so
save the --json output of the window before a change; it cannot be recounted later.

Run: python scripts/count_clarifications.py [--days 30] [--until YYYY-MM-DD] [--show] [--json]
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


# Records that are in the transcript but were not typed by the user: subagent turns,
# injected caveats, /compact summaries, and transcript-only notices.
NOT_TYPED = ("isSidechain", "isMeta", "isCompactSummary", "isVisibleInTranscriptOnly")
# Prompts handed over by automation (`claude -p`, SDK scripts), not by a person.
AUTOMATED_ENTRYPOINTS = ("sdk-cli",)


def typed_text(record: dict) -> str | None:
    """The text the user typed in this transcript record, or None if it is not one.

    A message can hold several text blocks. Blocks that start with "<" are added by
    the client or the harness (the IDE's open-file note, command output, hook text)
    and are dropped one by one, so what the user typed next to them still counts.
    """
    if record.get("type") != "user" or any(record.get(k) for k in NOT_TYPED):
        return None
    if record.get("entrypoint") in AUTOMATED_ENTRYPOINTS:
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        blocks = [c.get("text", "") for c in content
                  if isinstance(c, dict) and c.get("type") == "text"]
    else:
        return None
    kept = [b.strip() for b in blocks if isinstance(b, str)]
    kept = [b for b in kept if b and not b.startswith("<")]
    return "\n".join(kept) or None


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


def scan(root: Path, since: datetime.date, until: datetime.date,
         max_chars: int) -> tuple[dict, list]:
    """Per-day counts and the matching messages, for days from `since` to `until`."""
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
            if text is None or day is None or not since <= day <= until or len(text) > max_chars:
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
    ap.add_argument("--days", type=int, default=30,
                    help="this many days, ending on --until (default 30)")
    ap.add_argument("--until", type=datetime.date.fromisoformat, default=None,
                    help="last day counted, YYYY-MM-DD (default today); for before/after windows")
    ap.add_argument("--projects", type=Path, default=None, help="transcript directory")
    ap.add_argument("--max-chars", type=int, default=500, help="skip longer messages (default 500)")
    ap.add_argument("--show", action="store_true", help="also print the matching messages")
    ap.add_argument("--json", action="store_true", help="print JSON, for summing machines")
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("--days must be 1 or more")
    until = args.until or today or datetime.date.today()
    since = until - datetime.timedelta(days=args.days - 1)
    days, matches = scan(args.projects or projects_dir(), since, until, args.max_chars)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.json:
        payload = {"since": since.isoformat(), "until": until.isoformat(), "days": days}
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
