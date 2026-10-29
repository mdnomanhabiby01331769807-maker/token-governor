#!/usr/bin/env python3
"""Measure what can be measured without any model.

1. Footprint: tokens the skill adds to a session, and what loads when.
2. Output: what a naive tool call puts into context versus what token-governor puts there,
   in light mode (no task) and in long mode (a task is started), plus the follow-up read.
3. Break-even: how many later turns a saving must last to repay the skill files.

Token counts use the heuristic in scripts/tg.py (est). They are estimates, not billing data.
Writes evals/results/local.json and prints a table. Stdlib only, no network, no model calls.
"""

import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TG = os.path.join(ROOT, "scripts", "tg.py")
SKILL = os.path.join(ROOT, "SKILL.md")
LONG_REFERENCE = os.path.join(ROOT, "references", "long-tasks.md")

os.environ.setdefault("TG_DIR", os.path.join(tempfile.gettempdir(), "tg-measure-import"))
_spec = importlib.util.spec_from_file_location("tg_module", TG)
tg_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg_module)
est = tg_module.est

SCENARIOS = {
    "api_log_2000_lines": (
        "for i in range(1, 2001):\n"
        "    lvl = 'ERROR' if i in (700, 1500) else 'INFO'\n"
        "    code = 500 if lvl == 'ERROR' else 200\n"
        "    print('2026-10-28T10:00:00Z', lvl, 'svc=api req=%d latency_ms=%d path=/v1/items/%d status=%d'"
        " % (i, (i * 37) % 900, i % 97, code))\n"
    ),
    "test_failure_300_lines": (
        "import sys\n"
        "failed = {57, 133, 201, 288, 299, 300}\n"
        "for i in range(1, 301):\n"
        "    if i in failed:\n"
        "        print('test_case_%03d ... FAILED: expected 200, got 500' % i)\n"
        "    else:\n"
        "        print('test_case_%03d ... ok' % i)\n"
        "print('AssertionError: 6 failures')\n"
        "sys.exit(1)\n"
    ),
    "medium_100_lines": (
        "for i in range(100):\n"
        "    print('line %03d padding text for the size check' % i)\n"
    ),
    "small_command_8_lines": (
        "for i in range(1, 9):\n"
        "    print('step', i, 'done')\n"
    ),
}


def run_direct(path):
    p = subprocess.run([sys.executable, path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    return p.stdout.decode("utf-8", "replace")


def tg_cli(work, state, *args):
    """Run tg with its own state folder, so light and long runs never share a task."""
    env = dict(os.environ, TG_DIR=os.path.join(work, state))
    env.pop("TG_PASS_TOKENS", None)
    p = subprocess.run([sys.executable, TG, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=env, cwd=work, timeout=300)
    return p.stdout.decode("utf-8", "replace")


def footprint():
    with open(SKILL, encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    front, body = m.group(1), text[m.end():]
    description = re.search(r"^description:\s*(.*)$", front, re.M).group(1)
    with open(LONG_REFERENCE, encoding="utf-8") as f:
        long_reference = f.read()
    call = "python3 <skill_dir>/scripts/tg.py run --name build -- python3 build.py"
    return {"description_tokens": est(description),
            "body_tokens": est(body),
            "long_reference_tokens": est(long_reference),
            "tg_call_text_tokens": est(call)}


def measure(work, name, source, task):
    path = os.path.join(work, name + ".py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    state = f"state-{name}-{'long' if task else 'light'}"
    if task:
        tg_cli(work, state, "init", "--goal", f"measure {name}", "--tier", "T2")
    raw = run_direct(path)
    shown = tg_cli(work, state, "run", "--name", name, "--", sys.executable, path)
    m = re.search(r"handle=(\S+)", shown)
    row = {"raw_tokens": est(raw), "tg_first_response_tokens": est(shown), "stashed": bool(m)}
    if m and name == "api_log_2000_lines":
        row["tg_followup_tokens"] = est(tg_cli(work, state, "peek", m.group(1), "--errors"))
    return row


def print_table(result):
    fp = result["footprint"]
    print("Skill footprint (heuristic tokens)")
    print(f"  description, in every session:            {fp['description_tokens']}")
    print(f"  SKILL.md body, when the skill loads:       {fp['body_tokens']}")
    print(f"  references/long-tasks.md, long work only:  {fp['long_reference_tokens']}")
    print(f"  one tg call, command text:                 {fp['tg_call_text_tokens']}")
    print()
    width = 40
    print(f"{'scenario':{width}} {'naive':>8} {'with tg':>9} {'follow-up':>10} {'stashed':>8}")
    for name, s in result["scenarios"].items():
        follow = s.get("tg_followup_tokens", "-")
        print(f"{name:{width}} {s['raw_tokens']:>8} {s['tg_first_response_tokens']:>9} "
              f"{str(follow):>10} {str(s['stashed']):>8}")
    print()
    for name, b in result["breakeven"].items():
        print(f"{name}: saves ~{b['saved_per_later_turn']} tokens per later turn; "
              f"light body repaid after {b['later_turns_to_repay_light_body']} later turn(s); "
              f"long-task files after {b['later_turns_to_repay_long_task_files']}")


def main():
    work = tempfile.mkdtemp(prefix="tg-measure-")
    try:
        fp = footprint()
        scenarios = {}
        for name, src in SCENARIOS.items():
            if name == "medium_100_lines":
                scenarios["medium_100_lines, light (no task)"] = measure(work, name, src, task=False)
                scenarios["medium_100_lines, long (task started)"] = measure(work, name, src, task=True)
            else:
                scenarios[name] = measure(work, name, src, task=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    breakeven = {}
    for name in ("api_log_2000_lines", "test_failure_300_lines"):
        s = scenarios[name]
        saved = s["raw_tokens"] - s["tg_first_response_tokens"] - fp["tg_call_text_tokens"]
        breakeven[name] = {
            "saved_per_later_turn": saved,
            "later_turns_to_repay_light_body":
                math.ceil(fp["body_tokens"] / saved) if saved > 0 else None,
            "later_turns_to_repay_long_task_files":
                math.ceil((fp["body_tokens"] + fp["long_reference_tokens"]) / saved) if saved > 0 else None,
        }
    result = {
        "method": "Heuristic token estimates from scripts/tg.py est(). Not billing data.",
        "tokenizer_caveat": ("Claude 4.7 and later tokenizers can produce about 30% more tokens for the "
                             "same text (platform pricing page). These counts may be low for those models."),
        "footprint": fp,
        "scenarios": scenarios,
        "breakeven": breakeven,
    }
    results_dir = os.path.join(HERE, "results")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "local.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print_table(result)


if __name__ == "__main__":
    main()
