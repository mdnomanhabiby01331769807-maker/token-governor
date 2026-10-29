# Costs and benchmark

## Short answer

- **Measured locally, with no model.** A 2,000-line API log enters the context as 254 tokens instead of 43,110 (plus 232 for a follow-up `peek --errors`). A 300-test run with 6 failures enters as 261 tokens instead of 1,623. A small command's output passes through unchanged: 24 tokens with tg, 24 without.
- **Projected with official prices.** A typical 15-turn long task costs 32–41% less with token-governor. A heavy 30-turn task costs 58–90% less. A small task that loads the skill costs 4–6% more, because nothing in it is large enough to save. That is why the skill's description asks for use only when output may be large or the work is long.
- **Not measured with a model yet.** The end-to-end saving is what a benchmark with real models would measure. Its runner is not in this release. A full run would cost about $6 on Haiku 5.5, $103 on Sonnet 5.5, or $207 on Opus 5.5, with caching on and typical task sizes. The pilot costs about $0.45, $7.74, or $15.49.

## What costs tokens

- **Every turn re-sends the whole context.** Input cost is the sum, over all turns, of the context size at each turn. A large tool result is paid for again on every later turn, not once.
- **Output tokens** (what the model writes) are billed once each, at the output price.
- **Prompt caching** makes the re-sent part cheaper. A cache read costs 0.1× the base input price on Haiku 5.5, and 0.05× on Sonnet 5.5 and Opus 5.5. A cache write costs 1.25× the base input price on all three models.
- **Haiku 5.5 has a cliff.** A request whose prompt is over 100,000 tokens pays five times the normal price on every price: input, output, cache writes and cache reads. A prompt of exactly 100,000 tokens stays in the lower tier.

## What is measured here

Source: `python3 evals/measure_local.py`, written to `evals/results/local.json`.

Token counts use the heuristic in `scripts/tg.py`: about 4 characters per token for ASCII text, and about 1.5 for other text, such as Bengali. They are estimates, not billing numbers. The heuristic is not calibrated against the platform's tokenizer.

| Case | Full output (tokens) | With tg (tokens) | Follow-up read (tokens) | Stored? |
|---|---:|---:|---:|---|
| 2,000-line API log | 43,110 | 254 | 232 (`peek --errors`) | yes |
| 300-test run, 6 failures | 1,623 | 261 | not measured | yes |
| 100-line output, light mode (no task) | 1,025 | 1,025 | — | no, printed unchanged |
| 100-line output, long mode (task started) | 1,025 | 144 | not measured | yes |
| 8-line command | 24 | 24 | — | no, printed unchanged |

**Skill footprint:**

- Description: 59 tokens. It is in every session where the skill is installed.
- SKILL.md body: 249 tokens. It loads when the skill is activated.
- `references/long-tasks.md`: 590 tokens. It loads only for long work.
- One `tg` call's command text: 18 tokens.

The body was 882 tokens in v0.1.0. It is shorter now because the long-task protocol moved to the reference file.

**Break-even:** a stored output saves its full size, minus the preview and the call, on every later turn. For the 300-test run that is 1,344 tokens per later turn. That repays the light body and the long-task files (839 tokens together) after one later turn. For the 2,000-line log the saving is 42,838 tokens per later turn. Small output saves nothing, which is why it passes through.

## Pass-through limits

Output at or below the limit is printed unchanged. Above it, output is stored behind a handle.

- **No active task (light mode): 1,500 estimated tokens.** Short work usually needs its output in full, and each extra tool call re-sends the whole context. This is a reasoned choice, not a measured optimum.
- **Active task (long mode): 400 estimated tokens.** Long work carries every raw output through every later turn, so big output is stored sooner.
- `TG_PASS_TOKENS` overrides both.

## Projected costs

**Assumptions** (all in `evals/cost_model.py`; edit them to test other shapes):

- **Small task:** 4 turns. Base context 3,000 tokens. Each turn adds 150 output tokens and 300 tokens of small results. No large output. With tg, the skill body (249 tokens) is in context from turn 1.
- **Typical task (T2, long mode):** 15 turns. Base context 8,000 tokens. Each turn adds 500 output tokens and 300 tokens of small results. Four results of 6,000 tokens arrive at turns 2, 5, 8 and 11. With tg, each becomes a 261-token preview plus an 18-token call. The body and long-task files (839 tokens) are in context from turn 1.
- **Heavy task:** 30 turns, with the same base and per-turn figures. Fourteen results of 8,000 tokens arrive at turns 2, 4, ..., 28.
- **Both conditions take the same number of turns.** No extra charge is made for follow-up reads, `peek`, `state` or `status` calls. Output is a fixed amount per turn in both conditions.
- **Prices:** USD per million tokens, from the [platform pricing page](https://platform.claude.com/docs/en/about-claude/pricing). Retrieved 2026-10-28 and checked again the same day. The page is undated, so check it again before you publish new numbers. The figures exclude the 1.1× US-only data-residency multiplier and the Batch API discount.

| Model | Input | Output | Cache write (5 min) | Cache read |
|---|---:|---:|---:|---:|
| Claude Haiku 5.5, up to 100,000 tokens | $0.10 | $0.50 | $0.125 | $0.01 |
| Claude Haiku 5.5, over 100,000 tokens | $0.50 | $2.50 | $0.625 | $0.05 |
| Claude Sonnet 5.5 | $2.00 | $10.00 | $2.50 | $0.10 |
| Claude Opus 5.5 | $4.00 | $20.00 | $5.00 | $0.20 |

**Largest single request (input tokens):** small task 4,350 without tg and 4,599 with tg. Typical task 43,200 without tg and 21,155 with tg. Heavy task 143,200 without tg, which is over the Haiku threshold, and 35,945 with tg.

**Cost per task (USD).** Input and output cost for the whole task, from `evals/cost_model.py`. "Change" is the cost with tg relative to without:

| Scenario | Model | Caching | No tg | With tg | Change |
|---|---|---|---:|---:|---:|
| Small | Haiku 5.5 | off | 0.0018 | 0.0019 | +6% |
| Small | Haiku 5.5 | on | 0.0009 | 0.0010 | +4% |
| Small | Sonnet 5.5 | off | 0.0354 | 0.0374 | +6% |
| Small | Sonnet 5.5 | on | 0.0179 | 0.0186 | +4% |
| Small | Opus 5.5 | off | 0.0708 | 0.0748 | +6% |
| Small | Opus 5.5 | on | 0.0358 | 0.0372 | +4% |
| Typical | Haiku 5.5 | off | 0.0445 | 0.0264 | −41% |
| Typical | Haiku 5.5 | on | 0.0128 | 0.0084 | −34% |
| Typical | Sonnet 5.5 | off | 0.8910 | 0.5271 | −41% |
| Typical | Sonnet 5.5 | on | 0.2195 | 0.1484 | −32% |
| Typical | Opus 5.5 | off | 1.7820 | 1.0543 | −41% |
| Typical | Opus 5.5 | on | 0.4390 | 0.2968 | −32% |
| Heavy | Haiku 5.5 | off | 0.7387 | 0.0747 | −90% |
| Heavy | Haiku 5.5 | on | 0.1282 | 0.0184 | −86% |
| Heavy | Sonnet 5.5 | off | 4.6860 | 1.4935 | −68% |
| Heavy | Sonnet 5.5 | on | 0.7205 | 0.3034 | −58% |
| Heavy | Opus 5.5 | off | 9.3720 | 2.9870 | −68% |
| Heavy | Opus 5.5 | on | 1.4410 | 0.6069 | −58% |

Reading the table:

- **Small tasks cost more with the skill loaded.** The increase is 4–6%, and the dollar amounts are tiny. Nothing in a small task is large, so the saving is zero and the body is the whole difference. Loading the skill for trivial work is not worth it.
- **Typical and heavy tasks cost less,** and the saving grows with the size of the task. On Haiku 5.5 without caching, the heavy task shows the largest saving (90%). Without tg the context passes 100,000 tokens and the five-times price applies. With tg it does not.
- **Caching lowers the cost in every case.** For typical and heavy tasks, the cost without caching is about 3 to 6.5 times the cost with caching. Long agent sessions usually run with caching, so the benchmark should too.

**What changed from v0.1.0:** the earlier projections left out the skill files. Version 0.2.0 counts them, which moves the typical and heavy savings by a few points. It also adds the small-task profile.

## The benchmark and its cost

A benchmark that would measure the end-to-end saving is designed but not yet run. Its task suite and runner are not in this release.

**Conditions:**

- **A:** no tool. The agent works without token-governor.
- **B1:** instructions only (SKILL.md, no scripts). This isolates the value of the instructions.
- **B2:** the full token-governor (SKILL.md, the reference file, and `tg.py`).

**Sizes:**

- **Pilot:** 5 tasks × 3 repetitions × 3 conditions = 45 runs.
- **Full:** 20 tasks × 5 repetitions × 2 agent platforms × 3 conditions = 600 runs. The two platforms are to be chosen before the run.

**The suite must cover every size.** It should include small tasks (the 4-turn profile), medium output (light and long mode), large output, and failures. Without small tasks, the cost of loading the skill for trivial work is not measured at all.

**Projected cost** for a typical task with caching on. B1 is costed like B2, so the figure is approximate:

| Model | Per task (3 conditions) | Pilot (45 runs) | Full (600 runs) |
|---|---:|---:|---:|
| Haiku 5.5 | $0.0297 | $0.45 | $5.94 |
| Sonnet 5.5 | $0.5162 | $7.74 | $103.25 |
| Opus 5.5 | $1.0325 | $15.49 | $206.50 |

These use typical task sizes. Heavier tasks cost more, and shorter ones cost less. Treat them as a planning figure until the pilot replaces the assumptions with measured sizes.

**How to spend the budget:**

1. Run the pilot first, on the cheapest model that can do the tasks at all. It checks the harness and the real task sizes.
2. Set a hard spending cap before the full run. If the cap is reached, stop and report partial results.
3. Fix the success criteria before running anything (pre-registration). The proposed criteria: the pass rate is no more than 2 percentage points below the baseline, the median total tokens are at least 20% lower on typical and heavy tasks, and the overhead on small tasks is at most 10%. If the criteria fail, the result is published as a failure, not hidden.

## What is not known yet

- Whether the agent follows the protocol reliably in practice.
- Whether agents load the skill only when they should. The description's "use when" rule is untested.
- Whether the saving holds at equal success. A preview can hide a detail the agent needs, and then the agent spends extra turns to recover it. Those turns are not in the projections.
- The real token counts. The pricing page says Claude 4.7 and later tokenizers produce "approximately 30 percent more tokens for the same text", and that the exact increase "depends on the content and workload shape". The measured counts come from a generic heuristic that is not calibrated to any tokenizer, so they may be low for the newer models. If the increase applies to all text, absolute costs rise by about 30%, and the percentage changes should move little. That is an expectation, not a measurement.
- How prompt caching behaves on each platform that runs the skill.
- Costs for task shapes other than the profiles above.
- Output token counts. The model uses a fixed amount per turn in both conditions.

## How to report your own numbers

Reporting is voluntary. token-governor sends nothing automatically. If you run it and want to share a result, open an issue with this template:

```text
Agent and version:
Model ID:
Task (one line):
Task size (small / medium / long):
Condition (no tg / with tg):
Input tokens (from the platform's usage report):
Output tokens:
Cache read and write tokens, if shown:
Tool calls:
Outcome (pass or fail, and how it was checked):
```

## Sources

- Prices: [platform.claude.com pricing](https://platform.claude.com/docs/en/about-claude/pricing), checked 2026-10-28.
- Local measurements: `evals/measure_local.py`. Projections: `evals/cost_model.py`.
