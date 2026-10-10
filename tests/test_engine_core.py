import os
import threading
from datetime import datetime, timedelta

import pytest

from test_engine_fixtures import make_ws, write_task

from agentos import core

SAMPLE = """---
id: A-007
project: shop
title: "Draft: landing copy"   # quoted because of the colon
custom_key: keep me
owner: copy
status: todo
blocked_by:
  - A-001
  - A-002
evidence:
lock:
---

# Body stays

## Goal

Exact body, trailing spaces"""  + "\x20\x20\x20\n"


def test_frontmatter_parse_and_roundtrip_untouched(tmp_path):
    p = tmp_path / "A-007-x.md"
    p.write_text(SAMPLE, encoding="utf-8")
    t = core.read_task(p)
    assert t.meta["title"] == "Draft: landing copy"
    assert t.meta["custom_key"] == "keep me"
    assert t.list("blocked_by") == ["A-001", "A-002"]
    core.write_task_atomic(t)
    assert p.read_text(encoding="utf-8") == SAMPLE  # byte-identical when nothing changed


def test_frontmatter_change_keeps_unknown_keys_order_and_body(tmp_path):
    p = tmp_path / "A-007-x.md"
    p.write_text(SAMPLE, encoding="utf-8")
    t = core.read_task(p)
    t.meta["status"] = "in_progress"
    t.meta["new_key"] = "value: with colon"
    core.write_task_atomic(t)
    text = p.read_text(encoding="utf-8")
    assert "status: in_progress" in text
    assert "custom_key: keep me" in text
    assert "# quoted because of the colon" in text
    assert text.index("custom_key") < text.index("status: in_progress")
    assert text.endswith("Exact body, trailing spaces   \n")
    again = core.read_task(p)
    assert again.meta["new_key"] == "value: with colon"
    assert again.list("blocked_by") == ["A-001", "A-002"]


def test_crlf_and_bom_preserved(tmp_path):
    p = tmp_path / "A-001-x.md"
    p.write_bytes(b"\xef\xbb\xbf---\r\nid: A-001\r\nstatus: todo\r\n---\r\nbody\r\n")
    t = core.read_task(p)
    assert t.id == "A-001"
    t.meta["status"] = "blocked"
    core.write_task_atomic(t)
    raw = p.read_bytes()
    assert b"status: blocked\r\n" in raw and b"\r\nbody\r\n" in raw


def test_inline_list_and_empty_values(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("---\nid:\nblocked_by: [A-001, 'A-002']\ndue:\n---\n", encoding="utf-8")
    t = core.read_task(p)
    assert t.id == "" and t.list("blocked_by") == ["A-001", "A-002"] and t.get("due") == ""


def test_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    target = tmp_path / "f.md"
    target.write_text("old", encoding="utf-8")
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("held by indexer")
        return real(src, dst)

    monkeypatch.setattr(core.os, "replace", flaky)
    core.write_text_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert calls["n"] == 3
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_atomic_write_gives_up_and_leaves_original(tmp_path, monkeypatch):
    target = tmp_path / "f.md"
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr(core.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        core.write_text_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_file_guard_contention(tmp_path):
    lock = tmp_path / "g.lock"
    with core.file_guard(lock) as first:
        assert first
        with core.file_guard(lock, timeout_s=0.2) as second:
            assert second is False
    assert not lock.exists()
    with core.file_guard(lock) as again:
        assert again


def test_file_guard_takes_over_stale(tmp_path):
    lock = tmp_path / "g.lock"
    lock.write_text("dead")
    old = (datetime.now() - timedelta(minutes=10)).timestamp()
    os.utime(lock, (old, old))
    with core.file_guard(lock, timeout_s=0.2) as ok:
        assert ok


def test_task_lock_contention_and_threads(tmp_path):
    ws = make_ws(tmp_path)
    path = write_task(ws, "A-001")
    results = []
    barrier = threading.Barrier(4)

    def grab():
        barrier.wait()
        results.append(core.acquire_lock(path))

    threads = [threading.Thread(target=grab) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [r for r in results if r]
    assert len(winners) == 1
    assert core.read_task(path).get("lock") == winners[0]
    assert core.release_lock(path, "someone-else") is False
    assert core.release_lock(path, winners[0]) is True
    assert core.read_task(path).get("lock") == ""


def test_stale_and_future_locks_are_dead():
    now = datetime(2026, 10, 10, 12, 0)
    assert core.lock_alive("2026-10-10T11:00:00|h|1", now)
    assert not core.lock_alive("2026-10-10T10:00:00|h|1", now)
    assert not core.lock_alive("2030-01-01T00:00:00|h|1", now)
    assert not core.lock_alive("garbage", now)
    assert not core.lock_alive("2026-10-10T09:12:04+02:00|studio-laptop|48213",
                               datetime(2026, 10, 11, 0, 5))


def test_next_id_scans_whole_dir(tmp_path):
    tdir = tmp_path / "tasks"
    (tdir / "archive").mkdir(parents=True)
    (tdir / "A-002-x.md").write_text("---\nid: A-002\n---\n", encoding="utf-8")
    (tdir / "archive" / "A-009-old.md").write_text("---\nid: A-009\n---\n", encoding="utf-8")
    (tdir / "renamed.md").write_text("---\nid: A-011\n---\n", encoding="utf-8")
    (tdir / "H-030-human.md").write_text("---\nid: H-030\n---\n", encoding="utf-8")
    assert core.next_id(tdir, "A") == "A-031"  # counter shared with H-030
    assert core.next_id(tdir, "H") == "H-031"
    assert core.next_id(tmp_path, "A") == "A-031"  # project dir works too
    assert core.next_id(tmp_path / "missing", "A") == "A-001"


def test_create_task_never_overwrites(tmp_path):
    ws = make_ws(tmp_path)
    a = core.create_task(ws, "Write copy", owner="copy", project="shop")
    b = core.create_task(ws, "Write copy", owner="copy", project="shop")
    h = core.create_task(ws, "Sign it", owner="human", project="shop")
    assert (a.id, b.id, h.id) == ("A-001", "A-002", "H-003")
    inbox1 = core.create_task(ws, "Ad hoc", owner="research")
    inbox2 = core.create_task(ws, "Ad hoc", owner="research")
    assert inbox1.id == "" and inbox1.path != inbox2.path
    assert inbox2.path.name == "ad-hoc-2.md"


def test_set_status_requires_evidence(tmp_path):
    ws = make_ws(tmp_path)
    path = write_task(ws, "A-001")
    with pytest.raises(core.EvidenceRequired):
        core.set_status(path, "done")
    assert core.read_task(path).status == "todo"
    t = core.set_status(path, "done", evidence="materials/out.md", now=datetime(2026, 10, 10, 9))
    assert t.get("closed") == "2026-10-10" and t.get("evidence") == "materials/out.md"
    assert "status todo -> done" in core.read_task(path).section("Progress log")
    with pytest.raises(ValueError):
        core.set_status(path, "finished")
    reopened = core.set_status(path, "todo")
    assert reopened.get("closed") == ""


def test_decide_and_notes(tmp_path):
    ws = make_ws(tmp_path)
    path = write_task(ws, "H-001", type="decision", body="\n## For approval\n\nDo X.\n")
    t = core.decide(path, True, "go")
    assert t.status == "done" and t.get("decision") == "accepted" and t.get("evidence")
    body = core.read_task(path).body
    assert body.index("## For approval") < body.index("## Owner notes") < body.index("## Progress log")
    with pytest.raises(ValueError):
        core.decide(write_task(ws, "A-001"), True)
    core.add_note(path, "second note")
    assert core.read_task(path).section("Owner notes").count("\n- ") == 1


def test_run_now_requests(tmp_path):
    ws = make_ws(tmp_path)
    now = datetime(2026, 10, 10, 12)
    assert core.request_run_now(ws, "projects/shop/tasks/A-001-task.md", now=now) == "added"
    assert core.request_run_now(ws, "projects\\shop\\tasks\\A-001-task.md", now=now) == "duplicate"
    assert core.take_run_now(ws, now + timedelta(hours=5)) == []  # expired (TTL)
    core.request_run_now(ws, "inbox/x.md", now=now)
    taken = core.take_run_now(ws, now)
    assert [e["path"] for e in taken] == ["inbox/x.md"]
    assert core.take_run_now(ws, now) == []


def test_iter_tasks_skips_broken_files(tmp_path):
    ws = make_ws(tmp_path)
    write_task(ws, "A-001")
    (ws / "projects" / "shop" / "tasks" / "A-002-bad.md").write_bytes(b"---\nid: A-002\n\xff\xfe\n---\n")
    (ws / "projects" / "shop" / "tasks" / "notes.md").write_text("no frontmatter", encoding="utf-8")
    errors = []
    tasks = list(core.iter_tasks(ws, errors=errors))
    assert [t.id for t in tasks] == ["A-001"]
    assert len(errors) == 1
