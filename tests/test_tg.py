"""Tests for scripts/tg.py and the skill folder.

Run from the repository root:  python -m unittest discover -s tests -v
"""

import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TG = str(ROOT / "scripts" / "tg.py")
# 100 lines of about 40 characters: roughly 1,000 estimated tokens, between the two limits.
MEDIUM = "for i in range(100):\n    print('line %03d padding text for the size check' % i)\n"


def normal(text):
    return text.replace("\r\n", "\n")


class TgCliTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="tg-test-")
        self.env = dict(os.environ, TG_DIR=os.path.join(self.work, ".tg"))
        self.env.pop("TG_PASS_TOKENS", None)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def tg(self, *args, stdin=None):
        p = subprocess.run([sys.executable, TG, *args], input=stdin, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=self.env, cwd=self.work, timeout=120)
        err = p.stderr.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 0, f"tg {args} failed: {err}")
        return p.stdout.decode("utf-8", "replace")

    @staticmethod
    def handle_of(text):
        m = re.search(r"handle=(\S+)", text)
        if not m:
            raise AssertionError(f"no handle in output: {text[:200]!r}")
        return m.group(1)

    def test_version(self):
        p = subprocess.run([sys.executable, TG, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertIn(b"0.2.0", p.stdout)

    # light mode: no task, no setup

    def test_small_output_passes_through_unchanged(self):
        out = self.tg("run", "--", sys.executable, "-c", "print('alpha'); print('beta')")
        self.assertEqual(normal(out), "alpha\nbeta\n")

    def test_failed_small_command_marks_exit_code_last(self):
        out = self.tg("run", "--", sys.executable, "-c", "import sys; print('oops'); sys.exit(2)")
        self.assertEqual(normal(out).splitlines()[-1], "[exit 2]")

    def test_light_mode_keeps_no_task_and_no_ledger(self):
        self.tg("run", "--", sys.executable, "-c", "print('x')")
        self.assertFalse(pathlib.Path(self.work, ".tg", "current.json").exists())
        self.assertFalse(pathlib.Path(self.work, ".tg", "ledger.md").exists())

    def test_light_limit_is_higher_than_long_limit(self):
        cmd = ("run", "--name", "mid", "--", sys.executable, "-c", MEDIUM)
        light = self.tg(*cmd)
        self.assertNotIn("handle=", light)
        self.assertEqual(len(normal(light).splitlines()), 100)
        self.tg("init", "--goal", "limit check", "--tier", "T1")
        self.assertIn("handle=", self.tg(*cmd))

    def test_env_limit_overrides_both(self):
        self.env["TG_PASS_TOKENS"] = "50"
        out = self.tg("run", "--", sys.executable, "-c", MEDIUM)
        self.assertIn("handle=", out)

    def test_status_in_light_mode_says_so(self):
        self.assertIn("no active task", self.tg("status"))

    def test_note_done_and_usage_without_a_task_leave_no_trace(self):
        self.assertIn("no active task", self.tg("note", "NEXT: nothing"))
        self.assertIn("no active task", self.tg("usage", "--input", "5"))
        self.assertIn("no active task", self.tg("done", "--result", "nothing"))
        self.assertEqual(self.tg("history").strip(), "no history yet")
        self.assertFalse(pathlib.Path(self.work, ".tg", "ledger.md").exists())

    # stored output

    def test_large_failing_output_is_stashed_and_errors_are_visible(self):
        script = ("import sys\n"
                  "for i in range(3000):\n"
                  "    print('row', i)\n"
                  "print('ERROR: disk full')\n"
                  "sys.exit(3)\n")
        out = self.tg("run", "--name", "big", "--", sys.executable, "-c", script)
        self.assertIn("exit=3", out)
        self.assertIn("ERROR: disk full", out)
        h = self.handle_of(out)
        self.assertTrue(h.startswith("big_"))
        self.assertIn("ERROR: disk full", self.tg("peek", h, "--errors"))

    def test_small_stashed_output_shows_every_line(self):
        out = self.tg("run", "--always-stash", "--name", "eight", "--",
                      sys.executable, "-c", "for i in range(1, 9): print('line', i)")
        for i in range(1, 9):
            self.assertIn(f"line {i}", out)

    def test_peek_by_line_and_grep(self):
        data = "\n".join(f"n{i}" for i in range(1, 501)).encode()
        h = self.handle_of(self.tg("stash", "--always-stash", "--name", "nums", stdin=data))
        self.assertEqual(self.tg("peek", h, "--lines", "42").strip(), "42: n42")
        self.assertIn("49: n49", self.tg("peek", h, "--grep", "^n49$"))

    def test_bengali_round_trip(self):
        text = "বাংলা লগ: সার্ভার ত্রুটি\nদ্বিতীয় লাইন\n".encode("utf-8")
        h = self.handle_of(self.tg("stash", "--always-stash", "--name", "bn", stdin=text))
        self.assertIn(h, self.tg("find", "সার্ভার"))

    def test_cache_reuses_the_same_handle(self):
        args = ("run", "--cache", "60", "--always-stash", "--name", "u", "--",
                sys.executable, "-c", "import uuid; print(uuid.uuid4())")
        first = self.tg(*args)
        second = self.tg(*args)
        self.assertIn("CACHED", second)
        self.assertEqual(self.handle_of(first), self.handle_of(second))

    def test_timeout_is_reported(self):
        out = self.tg("run", "--timeout", "1", "--always-stash", "--name", "slow", "--",
                      sys.executable, "-c", "import time; time.sleep(10)")
        self.assertIn("timeout", out)

    # long mode: a started task

    def test_secrets_are_redacted_everywhere(self):
        text = ("config: password=hunter2\n"
                "key AKIAABCDEFGHIJKLMNOP\n"
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123\n")
        self.tg("init", "--goal", "redaction check", "--tier", "T1")
        self.tg("note", "NEXT: rotate token=sekrit123")
        out = self.tg("stash", "--always-stash", "--name", "sec", stdin=text.encode())
        for secret in ("hunter2", "AKIAABCDEFGHIJKLMNOP", "abcdefghijklmnopqrstuvwxyz0123", "sekrit123"):
            self.assertNotIn(secret, out)
        for path in pathlib.Path(self.work, ".tg", "store").glob("*.txt"):
            self.assertNotIn("hunter2", path.read_text(encoding="utf-8"))
        ledger = pathlib.Path(self.work, ".tg", "ledger.md").read_text(encoding="utf-8")
        self.assertNotIn("sekrit123", ledger)

    def test_status_stops_past_double_the_guide(self):
        self.tg("init", "--goal", "budget check", "--tier", "T1")
        for i in range(7):
            self.tg("note", f"NEXT: step {i}")
        self.assertIn("STOP", self.tg("status"))

    def test_t0_has_no_guide_and_never_stops(self):
        self.tg("init", "--goal", "quick answer", "--tier", "T0")
        for _ in range(5):
            self.tg("run", "--", sys.executable, "-c", "print('ok')")
        out = self.tg("status")
        self.assertIn("no tool-call guide", out)
        self.assertNotIn("STOP", out)

    def test_done_archives_each_task_and_flags_repeats(self):
        goal = "Summarize service error logs for incident review"
        for i in range(2):
            self.tg("init", "--goal", goal, "--tier", "T2")
            self.tg("done", "--result", f"run {i}")
        self.tg("init", "--goal", goal, "--tier", "T2")
        out = self.tg("done", "--result", "run 2")
        self.assertIn("REPEATED PATTERN", out)
        archives = list(pathlib.Path(self.work, ".tg", "archive").glob("*.md"))
        self.assertEqual(len(archives), 3)

    def test_state_folder_ignores_itself(self):
        self.tg("init", "--goal", "gitignore check", "--tier", "T1")
        gi = pathlib.Path(self.work, ".tg", ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*", gi)

    def test_no_network_or_telemetry_imports(self):
        src = pathlib.Path(TG).read_text(encoding="utf-8")
        for mod in ("socket", "urllib", "http", "requests", "ftplib", "smtplib", "xmlrpc", "ssl"):
            self.assertIsNone(re.search(rf"^\s*(import|from)\s+{mod}\b", src, re.M), mod)


class SkillFolderTest(unittest.TestCase):
    def test_skill_folder_validates(self):
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_skill.py"), str(ROOT)],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 0, p.stdout.decode("utf-8", "replace"))

    def test_long_task_reference_is_shipped(self):
        self.assertTrue((ROOT / "references" / "long-tasks.md").is_file())

    def test_validator_reports_a_missing_reference(self):
        spec = importlib.util.spec_from_file_location("validate_skill", ROOT / "tools" / "validate_skill.py")
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        with tempfile.TemporaryDirectory() as base:
            folder = os.path.join(base, "token-governor")
            os.mkdir(folder)
            with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: token-governor\ndescription: test\n---\n\nSee `references/missing.md`.\n")
            errors, _ = validator.validate(folder)
        self.assertTrue(any("references/missing.md" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
