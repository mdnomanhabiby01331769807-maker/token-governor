#!/usr/bin/env python3
"""Project what a benchmark would cost, from explicit assumptions and official list prices.

Inputs: evals/prices.json (official USD per million tokens) and, when present,
evals/results/local.json (measured size of a tg preview, a tg call, and the skill files).
Every assumption is a constant below. Replace them with pilot measurements when you have them.

Profiles:
  SMALL    four turns of small output, which passes through unchanged. The only cost with
           tg is the skill body, so this shows what loading the skill costs when it saves nothing.
  TYPICAL  a 15-turn long task with four large outputs (skill body and long-task files loaded).
  HEAVY    a 30-turn long task with fourteen large outputs (same skill files).

Stdlib only. No network, no model calls.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "prices.json"), encoding="utf-8") as f:
    PRICES = json.load(f)

LOCAL_PATH = os.path.join(HERE, "results", "local.json")
if os.path.exists(LOCAL_PATH):
    with open(LOCAL_PATH, encoding="utf-8") as f:
        LOCAL = json.load(f)
    PREVIEW_TOKENS = LOCAL["scenarios"]["test_failure_300_lines"]["tg_first_response_tokens"]
    CALL_TOKENS = LOCAL["footprint"]["tg_call_text_tokens"]
    BODY_TOKENS = LOCAL["footprint"]["body_tokens"]
    LONG_FILES_TOKENS = LOCAL["footprint"]["long_reference_tokens"]
else:
    PREVIEW_TOKENS, CALL_TOKENS, BODY_TOKENS, LONG_FILES_TOKENS = 300, 60, 200, 800

MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]

SMALL = {"name": "small task", "turns": 4, "base_context": 3000, "output_per_turn": 150,
         "small_result": 300, "big_at": [], "big_raw": 0, "skill_tokens": BODY_TOKENS}
TYPICAL = {"name": "typical T2 task", "turns": 15, "base_context": 8000, "output_per_turn": 500,
           "small_result": 300, "big_at": [2, 5, 8, 11], "big_raw": 6000,
           "skill_tokens": BODY_TOKENS + LONG_FILES_TOKENS}
HEAVY = {"name": "heavy task", "turns": 30, "base_context": 8000, "output_per_turn": 500,
         "small_result": 300, "big_at": list(range(2, 29, 2)), "big_raw": 8000,
         "skill_tokens": BODY_TOKENS + LONG_FILES_TOKENS}
PROFILES = (SMALL, TYPICAL, HEAVY)


def simulate(sc, use_tg):
    """Input size of every request, and the tokens each turn adds to the context.
    With tg, the skill files are in context from the first turn."""
    ctx = sc["base_context"] + (sc["skill_tokens"] if use_tg else 0)
    contexts, added = [], []
    for t in range(1, sc["turns"] + 1):
        contexts.append(ctx)
        new = sc["output_per_turn"] + sc["small_result"]
        if t in sc["big_at"]:
            new += (PREVIEW_TOKENS + CALL_TOKENS) if use_tg else sc["big_raw"]
        added.append(new)
        ctx += new
    return contexts, added


def run_cost(model, sc, use_tg, cache):
    p = PRICES["models"][model]
    contexts, added = simulate(sc, use_tg)
    threshold = p.get("long_context_threshold")
    multiplier = p.get("long_context_multiplier", 1.0)
    total = 0.0
    for t, ctx in enumerate(contexts):
        if cache:
            if t == 0:
                cost_in = ctx * p["cache_write_5m"]
            else:
                cost_in = contexts[t - 1] * p["cache_read"] + added[t - 1] * p["cache_write_5m"]
        else:
            cost_in = ctx * p["input"]
        cost_out = sc["output_per_turn"] * p["output"]
        factor = multiplier if threshold and ctx > threshold else 1.0
        total += factor * (cost_in + cost_out)
    return total / 1_000_000


def change(a, b):
    """Percent change with tg relative to without (positive means tg costs more)."""
    return (b / a - 1) * 100 if a else 0.0


def main():
    print(f"Prices: {PRICES['source']} (retrieved {PRICES['retrieved']}), USD per million tokens.")
    print(f"Preview per stashed output: {PREVIEW_TOKENS} tokens; tg call: {CALL_TOKENS} tokens.")
    print(f"Skill files with tg: body {BODY_TOKENS} tokens (small task); body plus long-task files "
          f"{BODY_TOKENS + LONG_FILES_TOKENS} tokens (long task).")
    print()
    print("Largest single request (input tokens)")
    for sc in PROFILES:
        no_tg, _ = simulate(sc, False)
        with_tg, _ = simulate(sc, True)
        print(f"  {sc['name']:16} no tg: {max(no_tg):>8,}   with tg: {max(with_tg):>8,}")
    print()
    print("Cost per task (USD)")
    print(f"{'scenario':16} {'model':18} {'cache':5} {'no tg':>9} {'with tg':>9} {'change':>8}")
    for sc in PROFILES:
        for model in MODELS:
            for cache in (False, True):
                a = run_cost(model, sc, False, cache)
                b = run_cost(model, sc, True, cache)
                print(f"{sc['name']:16} {model:18} {'on' if cache else 'off':5} "
                      f"{a:>9.4f} {b:>9.4f} {change(a, b):>+7.0f}%")
    print()
    print("Benchmark projection (typical task, prompt caching on)")
    print("  conditions: A = no tool, B1 = instructions only, B2 = full tool (B1 costed like B2)")
    print("  pilot: 5 tasks x 3 repetitions x 3 conditions = 45 runs")
    print("  full:  20 tasks x 5 repetitions x 2 platforms x 3 conditions = 600 runs")
    print(f"{'model':18} {'3 conditions/task':>18} {'pilot USD':>10} {'full USD':>10}")
    for model in MODELS:
        a = run_cost(model, TYPICAL, False, True)
        b = run_cost(model, TYPICAL, True, True)
        bundle = a + 2 * b
        print(f"{model:18} {bundle:>18.4f} {15 * bundle:>10.2f} {200 * bundle:>10.2f}")


if __name__ == "__main__":
    main()
