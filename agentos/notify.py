"""Notifications: effects only, batched, deduplicated. A quiet automation is a good one.

- The runner records EFFECTS (task done, status changed, new task) into a buffer.
- `digest()` sends one batched message in the configured hour slots (`digest_hours`),
  never one message per run. An empty buffer sends nothing.
- Technical failures (timeouts, limits, crashes) go to the log; at most ONE line per day
  about them reaches the digest. The owner wants to know what worked, not why cron failed.
- Dedupe is by content with times and numbers of minutes stripped, so the same message
  re-rendered with a fresh timestamp is not sent twice.
- Backends: none (buffer is consumed, nothing delivered), file (.agentos/digest.md),
  telegram (token and chat id ONLY from env or .env: AGENTOS_TELEGRAM_TOKEN,
  AGENTOS_TELEGRAM_CHAT_ID). The token never appears in logs.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from . import PRODUCT_NAME, core

BUFFER = "notify-buffer.jsonl"
FAILURES = "failures.jsonl"
STATE = "notified.json"
DEDUPE_DAYS = 7
TELEGRAM_MAX = 4000


def _state_path(ws) -> Path:
    return core.state_dir(ws) / STATE


def _append_jsonl(ws, name: str, record: dict) -> None:
    path = core.state_dir(ws) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with core.file_guard(str(path) + ".lock") as ok:
        if not ok:
            core.log(ws, "notify", f"buffer busy, dropped: {record.get('text', '')[:80]}")
            return
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def record_effect(workspace, kind: str, text: str, now: datetime | None = None) -> None:
    """kind: done | changed | new | note. Called by the runner, only for real effects."""
    _append_jsonl(workspace, BUFFER, {"when": core.stamp(now), "kind": kind, "text": text})


def record_failure(workspace, text: str, now: datetime | None = None) -> None:
    core.log(workspace, "failures", text)
    _append_jsonl(workspace, FAILURES, {"when": core.stamp(now), "text": text})


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                out.append(item)
    except OSError:
        pass
    return out


def fingerprint(text: str) -> str:
    """Stable across re-renders: drop dates, times and digit runs, normalise spacing."""
    norm = re.sub(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?", "", text)
    norm = re.sub(r"\b\d{1,2}:\d{2}\b", "", norm)
    norm = re.sub(r"\s+", " ", norm).strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def build_message(effects: list[dict], failure_count: int, product: str) -> str:
    sections = {"done": "Done", "changed": "Changed", "new": "New tasks", "note": "Notes"}
    parts = []
    for kind, heading in sections.items():
        items = list(dict.fromkeys(e["text"] for e in effects if e.get("kind") == kind))
        if items:
            parts.append(f"{heading}:\n" + "\n".join(f"- {i}" for i in items))
    if failure_count:
        parts.append(f"Technical issues today: {failure_count} (details in .agentos/logs).")
    if not parts:
        return ""
    return f"{product} — queue summary\n\n" + "\n\n".join(parts)


def _send_telegram(env: dict, text: str) -> tuple[bool, str]:
    token = env.get("AGENTOS_TELEGRAM_TOKEN", "").strip()
    chat = env.get("AGENTOS_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False, "AGENTOS_TELEGRAM_TOKEN / AGENTOS_TELEGRAM_CHAT_ID not set"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for start in range(0, len(text), TELEGRAM_MAX):
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[start:start + TELEGRAM_MAX],
                                       "disable_web_page_preview": "true"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
                if r.status != 200:
                    return False, f"telegram HTTP {r.status}"
        except (urllib.error.URLError, OSError) as exc:
            return False, str(exc).replace(token, "***")
    return True, "sent"


def _slot(now: datetime, hours: list[int]) -> str | None:
    """Current digest slot id, e.g. '2026-10-10T15', or None before the first slot."""
    past = [h for h in hours if h <= now.hour]
    return f"{now.date().isoformat()}T{max(past):02d}" if past else None


def digest(workspace, cfg: dict | None = None, now: datetime | None = None,
           force: bool = False, sender=None) -> dict:
    """Deliver batched effects if a slot is due (or force). Returns what happened."""
    ws = Path(workspace)
    cfg = cfg or core.load_config(ws)
    now = now or core.now_local(cfg)
    kind = cfg["notify"]["kind"]
    state_path = _state_path(ws)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    slot = _slot(now, cfg["notify"]["digest_hours"])
    if not force and (slot is None or state.get("last_slot") == slot):
        return {"sent": False, "reason": "not a digest slot"}

    buf_path = core.state_dir(ws) / BUFFER
    effects = _read_jsonl(buf_path)
    today = now.date().isoformat()
    failures = [f for f in _read_jsonl(core.state_dir(ws) / FAILURES)
                if f.get("when", "").startswith(today)]
    failure_count = len(failures) if state.get("failure_line_date") != today else 0

    cutoff = (now - timedelta(days=DEDUPE_DAYS)).isoformat()
    seen = {k: v for k, v in (state.get("sent") or {}).items()
            if isinstance(v, str) and v >= cutoff}
    fresh = [e for e in effects if fingerprint(e["text"]) not in seen]
    message = build_message(fresh, failure_count, PRODUCT_NAME)

    result = {"sent": False, "reason": "nothing to report", "message": message}
    if message:
        if kind == "telegram":
            send = sender or _send_telegram
            ok, info = send(core.load_env(ws), message)
            if not ok:
                core.log(ws, "notify", f"telegram failed: {info}")
                return {"sent": False, "reason": info, "message": message}  # keep buffer
            result = {"sent": True, "reason": "telegram", "message": message}
        elif kind == "file":
            path = core.state_dir(ws) / "digest.md"
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"\n## {core.stamp(now)}\n\n{message}\n")
            result = {"sent": True, "reason": "file", "message": message}
        else:
            result = {"sent": False, "reason": "notify.kind = none", "message": message}
        for e in fresh:
            seen[fingerprint(e["text"])] = now.isoformat(timespec="seconds")
        if failure_count:
            state["failure_line_date"] = today

    with core.file_guard(str(buf_path) + ".lock") as ok:
        if ok and buf_path.exists():
            remaining = [e for e in _read_jsonl(buf_path) if e not in effects]
            core.write_text_atomic(buf_path, "".join(
                json.dumps(e, ensure_ascii=False) + "\n" for e in remaining))
    fail_path = core.state_dir(ws) / FAILURES
    keep_from = (now - timedelta(days=2)).date().isoformat()
    with core.file_guard(str(fail_path) + ".lock") as ok:
        if ok and fail_path.exists():
            kept = [f for f in _read_jsonl(fail_path) if f.get("when", "") >= keep_from]
            core.write_text_atomic(fail_path, "".join(
                json.dumps(f, ensure_ascii=False) + "\n" for f in kept))
    state["sent"] = seen
    if slot:
        state["last_slot"] = slot
    core.write_text_atomic(state_path, json.dumps(state, indent=2) + "\n")
    return result
