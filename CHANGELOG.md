# Changelog

## 0.2.0: fits small and long tasks

- **Light mode.** `run`, `stash`, `peek`, `find` and `ls` work with no task: no ledger, no budget, no state files. Output up to 1500 estimated tokens prints unchanged. Before, the limit was 400 and a header line was added.
- **Long mode.** After `init`, the stash limit is 400 tokens, as before. Notes, budget and state work as before.
- **Exit codes.** A failed command adds `[exit N]` on the last printed line. The header line is gone.
- **T0 has no tool-call guide.** Before, T0 had a guide of 0, so `status` said STOP after the first tg call.
- **No phantom tasks.** `done`, `note` and `usage` without a started task do nothing and say so. Before, `done` wrote an "untitled" history row.
- **Smaller skill.** SKILL.md is a short core: 249 tokens, down from 882. The long-task protocol moved to `references/long-tasks.md`, which loads only for long work. The description is 59 tokens.
- **Validator** checks `references/` paths as well as `scripts/`.
- **Cost model** counts the skill files in the tg condition (earlier projections left them out) and has a small-task profile.

## 0.1.0: first public release

- `scripts/tg.py`: single-file CLI, Python 3.9+, standard library only.
- Task lifecycle: `init`, `status`, `state`, `note`, `usage`, `done`, `history`, `report`.
- Output handling: `run`, `stash`, `peek`, `find`, `ls`, `prune`. `run` keeps exit codes, supports `--cache` for read-only commands and `--timeout`.
- Small output (at or below `TG_PASS_TOKENS`, default 400) is printed directly and not stored. `--always-stash` forces a handle.
- Redaction of common secret patterns (`TG_REDACT`), applied to output, notes and the ledger.
- Local-only state with its own `.gitignore`. No network access, no telemetry.
- Tests, a skill validator, and CI on Linux (Python 3.9 and 3.12), macOS and Windows.
- `evals/`: local measurement and cost projection scripts, with official prices in `evals/prices.json`.
- `docs/cost-and-benchmark.md` and `docs/cost-and-benchmark.bn.md`: measured numbers, projections with stated assumptions, what is still unknown, and the benchmark design, in English and Bangla.

Fixed before this release, in the internal prototype:

- A preview hid lines 6 to 10 of outputs between 6 and 10 lines long.
- Archive file names could collide within the same second and overwrite each other.
- The skill folder name did not match the `name` field, which the Agent Skills specification requires.
