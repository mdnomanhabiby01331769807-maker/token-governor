# Long tasks

Read this when the work has about 10 or more tool calls, touches several files, or may outlast the context window. Small work does not need it.

## Start the task
    tg.py init --goal "one-line goal" --tier T2

Tiers set a guide for tg calls, which `status` checks:
- T0: no guide. Quick work that still wants a ledger.
- T1: 3 calls. T2: 15 calls. T3: 50 calls.

Pick the lowest tier that works. Escalate only on evidence, and record it: `note "BUDGET: escalated to T3 because ..."`.

Once a task is started, the stash limit drops from 1500 to 400 estimated tokens, so big output is stored sooner. `TG_PASS_TOKENS` overrides this.

## After a context reset
Run `tg.py state` first. It prints the goal, the latest NEXT, OPEN and DECISION lines, and the handles you can still peek. Do not re-read old turns or re-run commands the ledger already covers.

## Keep the ledger current
- `note "NEXT: ..."`: keep the newest NEXT accurate.
- `note "DONE: ..."` when a step finishes.
- `note "DECISION: X because Y"`.
- `note "OPEN: ..."` for unresolved questions.

Notes are redacted for common secret patterns, but do not put secrets in them.

## Check the budget
`tg.py status` shows tg calls against the guide. On STOP, re-plan once and tell the user what changed. Cut scope, or batch several commands into one `run`.

## Delegate only when it pays
Send a subagent to read material only when all three hold: the source is large (roughly over 20k tokens), the question is narrow, and the answer can be a short list with evidence pointers. Brief it with the exact question, a format of at most 10 lines, and "return conclusions and line references, not raw text."

## Stop rules
- The same approach failed twice: change approach.
- Three steps in a row gave no new information: stop and report.
- Stop searching once every claim in the answer is backed by something you retrieved.

## Verify cheaply
Run the code, grep the claim, recompute the number, peek the source line.

## Finish and learn
    tg.py done --result "one line on what was produced"

`done` archives the ledger and records the task. If it prints REPEATED PATTERN, save a short skill for that procedure: its steps, pitfalls, and the exact commands that worked. Do not create skills for one-off tasks.

Without a started task, `done`, `note` and `usage` do nothing, and they say so.
