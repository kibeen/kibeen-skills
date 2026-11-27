"""scripts/count_clarifications.py against a throwaway transcript directory.

Run: python -m unittest discover -s tests
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date(2026, 11, 27)


def stamp(day: datetime.date, hour: int = 12) -> str:
    """Noon UTC, so the local day is the same day in every timezone a CI runner uses."""
    return "%sT%02d:00:00.000Z" % (day.isoformat(), hour)


def user(uuid: str, text, day: datetime.date = TODAY, **extra) -> dict:
    return {"type": "user", "uuid": uuid, "timestamp": stamp(day),
            "message": {"role": "user", "content": text}, **extra}


class CountClarificationsTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts")))
        import count_clarifications
        self.cc = count_clarifications
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, project: str, session: str, records: list) -> None:
        path = self.dir / project / ("%s.jsonl" % session)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in records]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_json(self, *argv: str) -> dict:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.cc.main(["--projects", str(self.dir), "--json", *argv], today=TODAY)
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_counts_only_what_the_user_typed(self):
        self.write("p", "s1", [
            user("u1", "B1은 뭐야?"),
            user("u2", "뭔말인지 모르겠어"),
            user("u3", [{"type": "text", "text": "이해가 안돼"}]),
            user("u4", "권장대로 해줘"),
            user("u5", [{"type": "tool_result", "content": "뭐야"}]),
            user("u6", "<command-name>/clear</command-name> 뭐야"),
            user("u7", "subagent prompt: 이게 뭐야", isSidechain=True),
            user("u8", "Caveat: 뭐야", isMeta=True),
            user("u9", "뭐야 " + "x" * 600),
            {"type": "assistant", "uuid": "a1", "timestamp": stamp(TODAY),
             "message": {"content": "무슨 뜻인지 설명"}},
            "not json",
            "[]",
        ])
        day = self.run_json()["days"][TODAY.isoformat()]
        self.assertEqual(day, {"messages": 4, "confused": 2, "asks": 1})

    def test_a_message_copied_into_a_resumed_session_counts_once(self):
        self.write("p", "s1", [user("u1", "site가 뭐야?")])
        self.write("p", "s2", [user("u1", "site가 뭐야?"), user("u2", "좋아")])
        day = self.run_json()["days"][TODAY.isoformat()]
        self.assertEqual(day, {"messages": 2, "confused": 0, "asks": 1})

    def test_days_before_the_window_are_left_out(self):
        old = TODAY - datetime.timedelta(days=7)
        self.write("p", "s1", [user("u1", "뭐야", day=old), user("u2", "뭐야")])
        self.assertEqual(list(self.run_json("--days", "7")["days"]), [TODAY.isoformat()])
        self.assertEqual(len(self.run_json("--days", "8")["days"]), 2)

    def test_subagent_transcripts_below_a_session_are_not_read(self):
        self.write("p", "s1", [user("u1", "좋아")])
        self.write("p/s1/subagents", "agent-1", [user("u2", "이게 뭐야")])
        day = self.run_json()["days"][TODAY.isoformat()]
        self.assertEqual(day["asks"], 0)

    def test_show_lists_the_matches(self):
        self.write("p", "s1", [user("u1", "transport replay가 뭐야?")])
        matches = self.run_json("--show")["matches"]
        self.assertEqual(matches, [{"day": TODAY.isoformat(), "kind": "asks",
                                    "text": "transport replay가 뭐야?"}])

    def test_the_table_reports_a_rate(self):
        self.write("p", "s1", [user("u1", "뭐야"), user("u2", "좋아")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.cc.main(["--projects", str(self.dir)], today=TODAY)
        self.assertIn("50.0%", out.getvalue().splitlines()[-1])

    def test_an_empty_directory_is_not_an_error(self):
        self.assertEqual(self.run_json()["days"], {})

    def test_a_window_below_one_day_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cc.main(["--projects", str(self.dir), "--days", "0"], today=TODAY)


if __name__ == "__main__":
    unittest.main()
