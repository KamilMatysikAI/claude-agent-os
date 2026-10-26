"""Usage report: dedupe of streamed replies, rewrite counting, alarms, bad lines. No real logs."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentos import usage  # noqa: E402

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _line(minutes_ago, msg_id, cw=0, cr=0, out=10, session="s1"):
    t = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return json.dumps({"type": "assistant", "timestamp": t, "sessionId": session, "requestId": "r" + msg_id,
                       "message": {"id": msg_id, "usage": {"input_tokens": 1, "output_tokens": out,
                                                          "cache_creation_input_tokens": cw,
                                                          "cache_read_input_tokens": cr}}})


def _write(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_dedupe_bad_lines_and_window(tmp_path):
    f = tmp_path / "p" / "s1.jsonl"
    _write(f, [_line(5, "a", cr=1000), _line(5, "a", cr=1000), "not json", '{"usage": 1}',
               _line(60 * 30, "old", cr=999999)])
    s = usage.file_stats(f, NOW - timedelta(hours=24))
    assert s["requests"] == 1 and s["cr"] == 1000


def test_runaway_subagent_is_flagged(tmp_path):
    main = tmp_path / "p" / "s1.jsonl"
    _write(main, [_line(i, f"m{i}", cr=50_000) for i in range(5)])
    agent = tmp_path / "p" / "s1" / "subagents" / "agent-x.jsonl"
    _write(agent, [_line(i * 10, f"x{i}", cw=400_000) for i in range(25)])
    (agent.with_name("agent-x.meta.json")).write_text(json.dumps({"description": "slow agent"}), encoding="utf-8")
    r = usage.analyze(tmp_path, 24, now=NOW)
    assert [a["description"] for a in r["alarms"]] == ["slow agent"]
    assert r["subagent_share"] > 0.9
    text = usage.report(r)
    assert "WARNING" in text and "slow agent" in text


def test_quiet_when_healthy_and_empty(tmp_path):
    _write(tmp_path / "p" / "s1.jsonl", [_line(i, f"m{i}", cr=500_000) for i in range(30)])
    r = usage.analyze(tmp_path, 24, now=NOW)
    assert r["alarms"] == []          # a long main session reading its cache is normal
    assert "No runaway agents" in usage.report(r)
    assert "No Claude Code usage" in usage.report(usage.analyze(tmp_path / "none", 24, now=NOW))


def test_streamed_reply_keeps_largest_output_and_bad_values_skip(tmp_path):
    f = tmp_path / "p" / "s1.jsonl"
    naive = json.dumps({"type": "assistant", "timestamp": "2026-10-26T11:00:00", "requestId": "rn",
                        "message": {"id": "n", "usage": {"output_tokens": 7}}})
    junk = json.dumps({"type": "assistant", "timestamp": NOW.isoformat(), "requestId": "rj",
                       "message": {"id": "j", "usage": {"output_tokens": "lots"}}})
    _write(f, [_line(5, "a", out=10), _line(5, "a", out=300), _line(5, "a", out=20), naive, junk])
    s = usage.file_stats(f, NOW - timedelta(hours=24))
    assert s["requests"] == 2 and s["out"] == 307


def test_one_hour_cache_weighs_more(tmp_path):
    f = tmp_path / "p" / "s1.jsonl"
    d = json.loads(_line(5, "a", cw=1000, out=0))
    d["message"]["usage"]["cache_creation"] = {"ephemeral_1h_input_tokens": 1000, "ephemeral_5m_input_tokens": 0}
    _write(f, [json.dumps(d)])
    s = usage.file_stats(f, NOW - timedelta(hours=24))
    assert s["cw"] == 0 and s["cw1h"] == 1000 and usage.weight(s) == 1 + 2000
