"""Token usage report from Claude Code session logs: which sessions and subagents burned the limit.

Reads `<config dir>/projects/**/*.jsonl` (default `~/.claude`, or `CLAUDE_CONFIG_DIR`), sums the
`usage` field per session and per subagent log, and flags the pattern that burns a weekly limit
fastest: a background agent that keeps rewriting its whole prompt cache (it waits longer than the
cache lifetime between calls) or grows a huge context.

Weights approximate relative cost (input 1, output 5, cache write 1.25 or 2 for the 1-hour cache,
cache read 0.1). They show
proportions, not your plan's exact limit accounting. Nothing leaves the machine.

    python -P -m agentos usage                 # last 24 hours
    python -P -m agentos usage --hours 168     # last week
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

WEIGHTS = {"inp": 1.0, "out": 5.0, "cw": 1.25, "cw1h": 2.0, "cr": 0.1}
BIG_WRITE = 100_000        # a cache write this large is a full context rewrite, not an increment
REWRITE_ALARM = 20         # full rewrites in the window that make a log suspicious
SUBAGENT_CONTEXT_ALARM = 300_000


def default_logs_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base).expanduser() / "projects"


def file_stats(path: Path, since: datetime) -> dict:
    """Usage of one log file since `since`. A malformed line is skipped, never fatal."""
    s = {"requests": 0, "inp": 0, "out": 0, "cw": 0, "cw1h": 0, "cr": 0, "rewrites": 0, "context_max": 0,
         "session": None, "description": None}
    replies = {}   # a streamed reply is logged several times with the same ids; keep the largest output
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
                msg = d.get("message") or {}
                u = msg.get("usage")
                if d.get("type") != "assistant" or not isinstance(u, dict):
                    continue
                t = datetime.fromisoformat(str(d["timestamp"]).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t < since:
                    continue
                cache = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
                row = {"inp": int(u.get("input_tokens") or 0), "out": int(u.get("output_tokens") or 0),
                       "cw": int(u.get("cache_creation_input_tokens") or 0),
                       "cw1h": int(cache.get("ephemeral_1h_input_tokens") or 0),
                       "cr": int(u.get("cache_read_input_tokens") or 0), "session": d.get("sessionId")}
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            key = (msg.get("id"), d.get("requestId"))
            if key in replies and key != (None, None):
                replies[key]["out"] = max(replies[key]["out"], row["out"])
            else:
                replies[key if key != (None, None) else len(replies)] = row
    for row in replies.values():
        row["cw1h"] = min(row["cw1h"], row["cw"])
        s["requests"] += 1
        s["inp"] += row["inp"]
        s["out"] += row["out"]
        s["cw1h"] += row["cw1h"]
        s["cw"] += row["cw"] - row["cw1h"]          # cw holds the 5-minute writes, cw1h the 1-hour ones
        s["cr"] += row["cr"]
        s["rewrites"] += row["cw"] > BIG_WRITE
        s["context_max"] = max(s["context_max"], row["inp"] + row["cw"] + row["cr"])
        s["session"] = s["session"] or row["session"]
    meta = path.with_name(path.name[:-len(".jsonl")] + ".meta.json")
    if meta.exists():
        try:
            s["description"] = json.loads(meta.read_text(encoding="utf-8")).get("description")
        except (OSError, ValueError, AttributeError):
            pass
    return s


def weight(s: dict) -> float:
    return sum(s[k] * w for k, w in WEIGHTS.items())


def analyze(logs_dir: Path, hours: float = 24, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    files = []
    for path in logs_dir.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < since.timestamp():
                continue
            s = file_stats(path, since)
        except OSError:
            continue
        if s["requests"]:
            s["file"] = str(path)
            s["subagent"] = "subagents" in path.parts
            s["weight"] = weight(s)
            files.append(s)
    total = sum(s["weight"] for s in files) or 1.0
    sessions = defaultdict(float)
    for s in files:
        sessions[s["session"]] += s["weight"]
    alarms = [s for s in files if s["rewrites"] >= REWRITE_ALARM
              or (s["subagent"] and s["context_max"] >= SUBAGENT_CONTEXT_ALARM)]
    return {
        "since": since, "total": total,
        "files": sorted(files, key=lambda s: -s["weight"]),
        "sessions": sorted(sessions.items(), key=lambda kv: -kv[1]),
        "subagent_share": sum(s["weight"] for s in files if s["subagent"]) / total,
        "alarms": sorted(alarms, key=lambda s: -s["weight"]),
    }


def report(r: dict) -> str:
    total = r["total"]
    if not r["files"]:
        return f"No Claude Code usage found since {r['since']:%Y-%m-%d %H:%M} UTC."
    out = [f"Usage since {r['since']:%Y-%m-%d %H:%M} UTC (weighted, proportions only)",
           f"Subagents: {100 * r['subagent_share']:.0f}% of the total", "", "Top 5 sessions:"]
    out += [f"  {100 * w / total:5.1f}%  {sid}" for sid, w in r["sessions"][:5]]
    out += ["", "Top 10 logs (session or subagent):"]
    for s in r["files"][:10]:
        name = s["description"] or Path(s["file"]).name
        out.append(f"  {100 * s['weight'] / total:5.1f}%  {name}  requests {s['requests']}, "
                   f"max context {s['context_max'] // 1000}k, full cache rewrites {s['rewrites']}")
    out.append("")
    if r["alarms"]:
        share = 100 * sum(s["weight"] for s in r["alarms"]) / total
        out.append(f"WARNING: {len(r['alarms'])} log(s) with {REWRITE_ALARM}+ full cache rewrites or a "
                   f"subagent context over {SUBAGENT_CONTEXT_ALARM // 1000}k used {share:.0f}% of the total.")
        out.append("Usual cause: a background agent waits (sleep loop, long test run) longer than the cache "
                   "lifetime, then pays for its whole context again. See rule 41.")
    else:
        out.append("No runaway agents found.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentos usage",
                                description="Token usage per session and subagent from Claude Code logs.")
    p.add_argument("--hours", type=float, default=24, help="look back this many hours (default 24)")
    p.add_argument("--logs", type=Path, default=None,
                   help="logs folder (default: $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects)")
    args = p.parse_args(argv)
    logs = args.logs or default_logs_dir()
    if not logs.is_dir():
        print(f"no Claude Code logs at {logs}")
        return 2
    print(report(analyze(logs, args.hours)))
    return 0
