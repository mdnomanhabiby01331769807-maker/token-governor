#!/usr/bin/env python3
"""token-governor: keep big tool output out of an agent's context.

Single file, Python 3.9+ standard library only. No network access, no telemetry.

State lives in $TG_DIR (default ./.tg). The folder ignores itself through its own
.gitignore, so it is never committed by accident.

Task lifecycle
  init --goal TEXT [--tier T0|T1|T2|T3]   start a task (an unfinished one is archived; T0 has no guide)
  status                                   tool-call count vs the tier guide
  state                                    compact summary; run first after a context reset
  note TEXT                                ledger line; prefixes DONE/NEXT/DECISION/OPEN/BUDGET
  usage --input N --output N               log real token counts when the platform reports them
  done [--result TEXT]                     finish: archive ledger, record history, pattern check
  history [-n N]                           finished and abandoned tasks
  report                                   savings estimate (current task and history)

Output
  run [--name N] [--cache SEC] [--timeout S] [--always-stash] -- CMD...
  stash [--name N] [--always-stash]        stash stdin (bytes-safe)
  peek HANDLE [--grep P] [-C N] [--lines A:B] [--head N] [--tail N] [--errors] [--max N]
  find PATTERN [--max N]                   search every stashed output
  ls                                       list stashed outputs
  prune [--hours H]                        delete old outputs (the current task's are kept)

Pass-through limit, in estimated tokens: 1500 with no active task (light mode, one-off work),
400 with an active task (long work: stash sooner). TG_PASS_TOKENS overrides both. Output at or
below the limit is printed unchanged, with `[exit N]` on the last line if the command failed.
Larger output is stored behind a handle. Light mode keeps no ledger and no budget; `init`
starts a task. Common secret patterns are redacted before output reaches the agent or the disk
(disable with TG_REDACT=0).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

__version__ = "0.2.0"

ROOT = os.environ.get("TG_DIR", ".tg")
STORE = os.path.join(ROOT, "store")
CUR = os.path.join(ROOT, "current.json")
LEDGER = os.path.join(ROOT, "ledger.md")
HISTORY = os.path.join(ROOT, "history.jsonl")
CACHE = os.path.join(ROOT, "cache.json")
ARCHIVE = os.path.join(ROOT, "archive")
PASS_LIGHT = 1500  # no active task: one-off work, printed unchanged up to this size
PASS_LONG = 400    # active task: stash sooner, so a long run does not carry raw output
REDACT_ON = os.environ.get("TG_REDACT", "1") != "0"

# tg invocations per tier. A floor for the total tool-call count, not the full count.
# None: no guide. Quick work keeps its ledger but is never told to stop.
TIER_BUDGET = {"T0": None, "T1": 3, "T2": 15, "T3": 50}
ERR_PAT = r"error|exception|traceback|fail|fatal|panic|denied|not found"
ERR_RX = re.compile(ERR_PAT, re.I)
LEDGER_RX = re.compile(r"^- \[\d\d:\d\d\] ([A-Z]+): (.*)$")
KIND_RX = re.compile(r"^(DONE|NEXT|DECISION|OPEN|BUDGET)\s*:\s*(.*)$", re.I | re.S)

SECRET_RULES = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[REDACTED private key]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED aws key id]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "[REDACTED github token]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED github token]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), "[REDACTED api key]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED slack token]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b((?:api[_-]?key|apikey|access[_-]?key|secret|token|passwd|password|pwd)"
                r"\s*[:=]\s*)(\"?)[^\s\"',;]+\2"), r"\1[REDACTED]"),
]


# ---------- helpers ----------

def est(text):
    """Heuristic token estimate: about 4 characters per token for ASCII, about 1.5 for
    other scripts (Bengali and similar cost more per character). Calibrate with real
    usage numbers when the platform reports them."""
    if not text:
        return 0
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return int((len(text) - non_ascii) / 4 + non_ascii / 1.5 + 0.999)


def redact(text):
    if not REDACT_ON:
        return text
    for rx, repl in SECRET_RULES:
        text = rx.sub(repl, text)
    return text


def ensure_root():
    os.makedirs(ROOT, exist_ok=True)
    gi = os.path.join(ROOT, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as f:
            f.write("# token-governor local state. Never commit this folder.\n*\n")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    ensure_root()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def new_task(goal, tier):
    return {"goal": goal, "tier": tier, "started": time.strftime("%Y-%m-%d %H:%M"),
            "started_ts": time.time(), "calls": 0, "stashes": 0, "peeks": 0,
            "stashed_tok": 0, "shown_tok": 0, "real_in": 0, "real_out": 0, "handles": []}


def cur():
    """The active task, or a placeholder for light mode. The placeholder is never saved."""
    return load_json(CUR, None) or new_task("untitled", "T2")


def task_active():
    return os.path.exists(CUR)


def pass_limit():
    if os.environ.get("TG_PASS_TOKENS"):
        try:
            return int(os.environ["TG_PASS_TOKENS"])
        except ValueError:
            sys.exit("TG_PASS_TOKENS must be a whole number of estimated tokens")
    return PASS_LONG if task_active() else PASS_LIGHT


def out(text, c):
    print(text)
    c["shown_tok"] += est(text)


def ledger_add(kind, body):
    ensure_root()
    body = redact(body.replace("\n", " "))
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(f"- [{time.strftime('%H:%M')}] {kind}: {body}\n")


def parse_ledger():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            matches = [LEDGER_RX.match(line.rstrip("\n")) for line in f]
    except FileNotFoundError:
        return []
    return [(m.group(1), m.group(2)) for m in matches if m]


def archive_ledger(tag):
    if os.path.exists(LEDGER):
        os.makedirs(ARCHIVE, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}-{tag}.md"
        shutil.move(LEDGER, os.path.join(ARCHIVE, name))


def append_history(c, status):
    rec = {k: c.get(k) for k in ("goal", "tier", "calls", "stashes", "stashed_tok",
                                 "shown_tok", "real_in", "real_out")}
    rec.update(status=status, ts=time.strftime("%Y-%m-%d %H:%M"),
               minutes=round((time.time() - c.get("started_ts", time.time())) / 60, 1))
    ensure_root()
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_history():
    rows = []
    try:
        with open(HISTORY, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return rows


def words(text):
    return {w for w in re.split(r"[\s,.;:!?()\[\]{}'\"/\\-]+", text.lower()) if len(w) > 2}


def similar_count(goal, tier):
    gw = words(goal)
    n = 0
    for r in read_history():
        if r.get("status") != "done" or r.get("tier") != tier:
            continue
        w = words(r.get("goal") or "")
        if gw and w and len(gw & w) / len(gw | w) >= 0.3:
            n += 1
    return n


# ---------- stashed outputs ----------

def hname(path):
    return os.path.basename(path)[:-4]


def handle_path(h):
    p = os.path.join(STORE, h + ".txt")
    if not os.path.exists(p):
        sys.exit(f"unknown handle '{h}' (see: tg.py ls)")
    return p


def read_handle(h):
    with open(handle_path(h), encoding="utf-8", errors="replace") as f:
        return f.read()


def list_handles():
    if not os.path.isdir(STORE):
        return []
    paths = [os.path.join(STORE, f) for f in os.listdir(STORE) if f.endswith(".txt")]
    return sorted(paths, key=os.path.getmtime, reverse=True)


def store_output(text, name, c, note=""):
    ensure_root()
    os.makedirs(STORE, exist_ok=True)
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", name or "out").strip("_")[:24] or "out"
    digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:6]
    h = f"{base}_{digest}"
    with open(os.path.join(STORE, h + ".txt"), "w", encoding="utf-8") as f:
        f.write(text)
    tok = est(text)
    c["stashes"] += 1
    c["stashed_tok"] += tok
    c["handles"].append(h)
    extra = f" | {note}" if note else ""
    if task_active():
        ledger_add("HANDLE", f"{h} lines={len(text.splitlines())} ~tok={tok}{extra}")
    return h


def preview(h, text, code=None):
    lines = text.splitlines()
    n = len(lines)
    head = f"handle={h} lines={n} ~tok={est(text)}"
    if code is not None:
        head += f" exit={code}"
    res = [head]
    if n <= 12:
        res += [line[:200] for line in lines]
    elif code not in (None, 0):
        # On failure the useful part is the error lines and the end, not the start.
        errs = [f"{i + 1}: {line[:200]}" for i, line in enumerate(lines) if ERR_RX.search(line)]
        if errs:
            res += [f"--- error lines ({len(errs)}) ---"] + errs[:12]
        res += ["--- tail ---"] + [line[:200] for line in lines[-20:]]
    else:
        res += ["--- head ---"] + [line[:200] for line in lines[:5]]
        res += ["--- tail ---"] + [line[:200] for line in lines[-5:]]
    res.append(f"(more: tg.py peek {h} --errors | --grep PAT | --lines A:B)")
    return "\n".join(res)


def emit_output(text, code, name, c, note, always_stash):
    """Print output at or below the pass limit unchanged, with no header; store and preview the
    rest. A failed command gets its exit code on the last line. Returns the handle or None."""
    if not always_stash and est(text) <= pass_limit():
        if not text:
            body = "(no output)"
        else:
            body = text[:-1] if text.endswith("\n") else text
        if code not in (None, 0):
            body += f"\n[exit {code}]"
        out(body, c)
        return None
    h = store_output(text, name, c, note)
    out(preview(h, text, code), c)
    return h


# ---------- commands ----------

def cmd_init(a, c):
    old = load_json(CUR, None)
    if old:
        append_history(old, "abandoned")
    archive_ledger("abandoned")
    nc = new_task(redact(a.goal), a.tier)
    ledger_add("BUDGET", f"tier={a.tier} goal={a.goal}")
    guide = TIER_BUDGET[a.tier]
    basis = "no tool-call guide" if guide is None else f"tool-call guide {guide}"
    out(f"started: {nc['goal']} (tier {a.tier}, {basis})", nc)
    return nc


def cmd_run(a, c):
    cmd = list(a.cmd)
    if cmd[:1] == ["--"]:
        cmd = cmd[1:]
    if not cmd:
        sys.exit("usage: tg.py run [--name N] [--cache SEC] -- COMMAND")
    label = " ".join(cmd)
    key = hashlib.sha1(label.encode("utf-8", "replace")).hexdigest()
    cache = load_json(CACHE, {})
    hit = cache.get(key) if a.cache else None
    if hit and time.time() - hit["ts"] < a.cache and os.path.exists(os.path.join(STORE, hit["handle"] + ".txt")):
        out("CACHED: same command ran recently, not re-run\n"
            + preview(hit["handle"], read_handle(hit["handle"]), hit["code"]), c)
        return c
    shell = len(cmd) == 1  # one string -> shell syntax (pipes, &&); several words -> plain argv
    try:
        p = subprocess.run(cmd[0] if shell else cmd, shell=shell, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=a.timeout)
        text, code = p.stdout.decode("utf-8", "replace"), p.returncode
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or b"").decode("utf-8", "replace")
        text, code = partial + f"\n[timeout after {a.timeout}s]", "timeout"
    except FileNotFoundError as e:
        text, code = str(e), 127
    text = redact(text)
    h = emit_output(text, code, a.name or "run", c, f"exit={code} cmd={label[:80]}", a.always_stash)
    if a.cache and h:
        cache[key] = {"handle": h, "ts": time.time(), "code": code}
        save_json(CACHE, cache)
    return c


def cmd_stash(a, c):
    text = redact(sys.stdin.buffer.read().decode("utf-8", "replace"))
    emit_output(text, None, a.name or "stdin", c, "stdin", a.always_stash)
    return c


def cmd_peek(a, c):
    lines = read_handle(a.handle).splitlines()
    n = len(lines)
    grep, ctx = a.grep, a.C
    if a.errors:
        grep, ctx = ERR_PAT, max(ctx, 2)
    if grep:
        rx = re.compile(grep, re.I)
        hits = [i for i, line in enumerate(lines) if rx.search(line)]
        c["peeks"] += 1
        if not hits:
            out("no match", c)
            return c
        keep = set()
        for i in hits:
            keep.update(range(max(0, i - ctx), min(n, i + ctx + 1)))
        idx = sorted(keep)
    elif a.lines:
        s, sep, e = a.lines.partition(":")
        if sep:
            lo, hi = int(s or 1), int(e or n)
        else:
            lo = hi = int(s)
        idx = list(range(max(1, lo) - 1, min(n, hi)))
    elif a.tail:
        idx = list(range(max(0, n - a.tail), n))
    else:
        idx = list(range(min(n, a.head or 20)))
    c["peeks"] += 1
    total = len(idx)
    idx = idx[: a.max]
    res, prev = [], None
    for i in idx:
        if prev is not None and i != prev + 1:
            res.append("...")
        res.append(f"{i + 1}: {lines[i][:300]}")
        prev = i
    if total > len(idx):
        res.append(f"[truncated: {total - len(idx)} more lines; narrow the pattern or raise --max]")
    out("\n".join(res) or "empty range", c)
    return c


def cmd_find(a, c):
    rx = re.compile(a.pattern, re.I)
    res = []
    for p in list_handles():
        with open(p, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if rx.search(line):
                    res.append(f"{hname(p)}:{i}: {line.rstrip()[:160]}")
                    if len(res) >= a.max:
                        break
        if len(res) >= a.max:
            break
    c["peeks"] += 1
    out("\n".join(res) or "no match", c)
    return c


def cmd_ls(a, c):
    rows = []
    for p in list_handles()[:30]:
        h = hname(p)
        t = read_handle(h)
        age = int((time.time() - os.path.getmtime(p)) / 60)
        rows.append(f"{h}  lines={len(t.splitlines())} ~tok={est(t)} age={age}m")
    out("\n".join(rows) or "no stashed outputs", c)
    return c


def cmd_note(a, c):
    if not task_active():
        out("no active task: note not saved. Start long work with init --goal ... to keep notes.", c)
        return c
    text = a.text.strip()
    m = KIND_RX.match(text)
    kind, body = (m.group(1).upper(), m.group(2)) if m else ("NOTE", text)
    ledger_add(kind, body)
    out("ok", c)
    return c


def cmd_state(a, c):
    if not os.path.exists(CUR):
        out("no active task: run `init --goal ... --tier T2` first", c)
        return c
    led = parse_ledger()
    rows = [f"GOAL: {c['goal']} | tier {c['tier']} | tg-calls {c['calls']} | started {c['started']}"]
    for kind, k in (("NEXT", 3), ("OPEN", 5), ("DECISION", 5), ("DONE", 5)):
        items = [body for kd, body in led if kd == kind][-k:]
        if items:
            rows.append(f"{kind}:")
            rows += [f"  - {body[:200]}" for body in items]
    hs = c.get("handles", [])[-8:]
    if hs:
        rows.append("HANDLES (peek or find these): " + ", ".join(hs))
    out("\n".join(rows), c)
    return c


def cmd_status(a, c):
    if not task_active():
        out("no active task (light mode): nothing to track. Use init --goal ... for a ledger and a guide.", c)
        return c
    guide = TIER_BUDGET.get(c["tier"])
    rows = [f"goal: {c['goal']}",
            f"tier {c['tier']}: tg-calls {c['calls']}"
            + (", no tool-call guide" if guide is None else f" / guide {guide}"),
            f"stashed {c['stashes']} outputs (~{c['stashed_tok']} tok), peeks {c['peeks']}, "
            f"shown ~{c['shown_tok']} tok"]
    if guide is not None and c["calls"] > 2 * guide:
        rows.append("STOP: more than 2x the tier guide. Re-plan once and tell the user what changed.")
    elif guide is not None and c["calls"] > guide:
        rows.append("Over the tier guide: cut scope, batch with `run`, or escalate the tier with a BUDGET note.")
    out("\n".join(rows), c)
    return c


def cmd_usage(a, c):
    if not task_active():
        out("no active task: usage not recorded", c)
        return c
    c["real_in"] += a.input
    c["real_out"] += a.output
    out(f"logged: input={a.input} output={a.output} "
        f"(task total in={c['real_in']} out={c['real_out']})", c)
    return c


def cmd_done(a, c):
    if not task_active():
        out("no active task: nothing to finish", c)
        return c
    if a.result:
        ledger_add("DONE", a.result)
    sim = similar_count(c["goal"], c["tier"])  # counted before this task is recorded
    append_history(c, "done")
    archive_ledger("done")
    saved = max(0, c["stashed_tok"] - c["shown_tok"])
    msg = [f"done: {c['goal']} | tg-calls {c['calls']} | kept out of context ~{saved} tok (estimate)"]
    if sim >= 2:
        msg.append(f"REPEATED PATTERN: {sim + 1} finished tasks at tier {c['tier']} look alike. "
                   "Save a short skill for this procedure.")
    out("\n".join(msg), c)
    return None  # clears the current task


def cmd_history(a, c):
    rows = read_history()[-a.n:]
    lines = []
    for r in rows:
        saved = max(0, (r.get("stashed_tok") or 0) - (r.get("shown_tok") or 0))
        lines.append(f"{r.get('ts')} {r.get('status')} [{r.get('tier')}] calls={r.get('calls')} "
                     f"kept-out~{saved} :: {(r.get('goal') or '')[:100]}")
    out("\n".join(lines) or "no history yet", c)
    return c


def cmd_report(a, c):
    done = [r for r in read_history() if r.get("status") == "done"]
    st = sum(r.get("stashed_tok") or 0 for r in done)
    sh = sum(r.get("shown_tok") or 0 for r in done)
    real = sum((r.get("real_in") or 0) + (r.get("real_out") or 0) for r in done)
    now = (f"current task: tg-calls={c['calls']} stashed~{c['stashed_tok']} shown~{c['shown_tok']} "
           f"real_tokens={c['real_in'] + c['real_out']}") if task_active() else "no active task (light mode)"
    lines = [
        now,
        f"finished tasks: {len(done)} | stashed~{st} shown~{sh} kept-out~{max(0, st - sh)} | "
        f"real tokens logged={real}",
        "Estimates are heuristic. 'real' counts only what was logged with `usage`.",
    ]
    out("\n".join(lines), c)
    return c


def cmd_prune(a, c):
    cutoff = time.time() - a.hours * 3600
    keep = set(c.get("handles", []))
    n = 0
    for p in list_handles():
        if hname(p) not in keep and os.path.getmtime(p) < cutoff:
            os.remove(p)
            n += 1
    out(f"pruned {n} outputs older than {a.hours}h (current task's handles kept)", c)
    return c


COMMANDS = {"init": cmd_init, "run": cmd_run, "stash": cmd_stash, "peek": cmd_peek,
            "find": cmd_find, "ls": cmd_ls, "note": cmd_note, "state": cmd_state,
            "status": cmd_status, "usage": cmd_usage, "done": cmd_done,
            "history": cmd_history, "report": cmd_report, "prune": cmd_prune}


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"tg {__version__}")
    sp = ap.add_subparsers(dest="command", required=True)

    p = sp.add_parser("init")
    p.add_argument("--goal", required=True)
    p.add_argument("--tier", default="T2", choices=sorted(TIER_BUDGET))

    p = sp.add_parser("run")
    p.add_argument("--name")
    p.add_argument("--cache", type=int, default=0,
                   help="reuse the output of the same command for SEC seconds (read-only commands only)")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--always-stash", action="store_true")
    p.add_argument("cmd", nargs=argparse.REMAINDER)

    p = sp.add_parser("stash")
    p.add_argument("--name")
    p.add_argument("--always-stash", action="store_true")

    p = sp.add_parser("peek")
    p.add_argument("handle")
    p.add_argument("--grep")
    p.add_argument("-C", type=int, default=1)
    p.add_argument("--lines")
    p.add_argument("--head", type=int)
    p.add_argument("--tail", type=int)
    p.add_argument("--errors", action="store_true")
    p.add_argument("--max", type=int, default=120)

    p = sp.add_parser("find")
    p.add_argument("pattern")
    p.add_argument("--max", type=int, default=40)

    sp.add_parser("ls")

    p = sp.add_parser("note")
    p.add_argument("text")

    sp.add_parser("state")
    sp.add_parser("status")

    p = sp.add_parser("usage")
    p.add_argument("--input", type=int, default=0)
    p.add_argument("--output", type=int, default=0)

    p = sp.add_parser("done")
    p.add_argument("--result", default="")

    p = sp.add_parser("history")
    p.add_argument("-n", type=int, default=10)

    sp.add_parser("report")

    p = sp.add_parser("prune")
    p.add_argument("--hours", type=int, default=72)
    return ap


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    a = build_parser().parse_args()
    c = cur()
    c["calls"] += 1
    res = COMMANDS[a.command](a, c)
    if res is None:
        if os.path.exists(CUR):
            os.remove(CUR)
    elif os.path.exists(CUR) or a.command == "init":
        # Read-only calls without a started task must not create a phantom task.
        save_json(CUR, res)


if __name__ == "__main__":
    main()
