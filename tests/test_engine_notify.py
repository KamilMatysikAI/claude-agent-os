from datetime import datetime

from test_engine_fixtures import make_ws

from agentos import core, notify


def _set_kind(ws, kind):
    toml = ws / "agentos.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('kind = "file"', f'kind = "{kind}"'),
                    encoding="utf-8")


def test_fingerprint_ignores_timestamps():
    a = notify.fingerprint("A-001 Draft copy done at 2026-10-10 14:02")
    b = notify.fingerprint("A-001 Draft copy done at 2026-10-11 09:15")
    assert a == b
    assert a != notify.fingerprint("A-002 Draft copy done")


def test_empty_digest_sends_nothing(tmp_path):
    ws = make_ws(tmp_path)
    res = notify.digest(ws, now=datetime(2026, 10, 10, 15, 5))
    assert res["sent"] is False
    assert not (ws / ".agentos/digest.md").exists()


def test_digest_batches_dedupes_and_respects_slots(tmp_path):
    ws = make_ws(tmp_path)
    t = datetime(2026, 10, 10, 15, 5)
    notify.record_effect(ws, "done", "A-001 Draft copy (shop)", t)
    notify.record_effect(ws, "done", "A-001 Draft copy (shop)", t)
    notify.record_effect(ws, "new", "A-002 Follow up (shop)", t)
    assert notify.digest(ws, now=datetime(2026, 10, 10, 7, 0))["sent"] is False  # before 8:00
    res = notify.digest(ws, now=t)
    assert res["sent"] and res["message"].count("A-001") == 1
    digest_file = (ws / ".agentos/digest.md").read_text(encoding="utf-8")
    assert "Done:" in digest_file and "New tasks:" in digest_file
    # same slot again: nothing; same effect re-recorded later: deduped
    notify.record_effect(ws, "done", "A-001 Draft copy (shop)", t)
    assert notify.digest(ws, now=t.replace(minute=40))["sent"] is False
    res = notify.digest(ws, now=datetime(2026, 10, 10, 21, 0))
    assert res["sent"] is False and res["reason"] == "nothing to report"


def test_failures_one_line_per_day(tmp_path):
    ws = make_ws(tmp_path)
    t = datetime(2026, 10, 10, 15, 5)
    for _ in range(3):
        notify.record_failure(ws, "timeout on A-001", t)
    res = notify.digest(ws, now=t)
    assert "Technical issues today: 3" in res["message"]
    notify.record_failure(ws, "timeout again", t)
    res = notify.digest(ws, now=t.replace(hour=21))
    assert res["sent"] is False  # failure line already reported today


def test_telegram_failure_keeps_buffer_and_hides_token(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    _set_kind(ws, "telegram")
    monkeypatch.setenv("AGENTOS_TELEGRAM_TOKEN", "123:secret")
    monkeypatch.setenv("AGENTOS_TELEGRAM_CHAT_ID", "42")
    t = datetime(2026, 10, 10, 8, 1)
    notify.record_effect(ws, "done", "A-001 Something (shop)", t)
    sent = []
    res = notify.digest(ws, now=t, sender=lambda env, text: (False, "network down"))
    assert res["sent"] is False
    assert (ws / ".agentos/notify-buffer.jsonl").read_text(encoding="utf-8").strip()
    res = notify.digest(ws, now=t, sender=lambda env, text: (sent.append((env, text)) or (True, "ok")))
    assert res["sent"] and sent[0][0]["AGENTOS_TELEGRAM_CHAT_ID"] == "42"
    assert (ws / ".agentos/notify-buffer.jsonl").read_text(encoding="utf-8") == ""
    log = core.state_dir(ws) / "logs" / "notify.log"
    assert "123:secret" not in log.read_text(encoding="utf-8")
