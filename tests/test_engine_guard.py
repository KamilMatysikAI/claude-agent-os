import shutil
from datetime import datetime

import pytest

from test_engine_fixtures import DEMO, make_ws, write_task

from agentos import core, guard

NOW = datetime(2026, 10, 10, 12, 0)


def _files(ws):
    return sorted(p.name for p in ws.rglob("*.md"))


def test_blocked_without_unblocker_creates_human_task(tmp_path):
    ws = make_ws(tmp_path)
    path = write_task(ws, "A-001", status="blocked",
                      body="\n## Unblocking action\n\nPaste the API key into .env.\n\n## Progress log\n\n")
    res = guard.run_guard(ws, now=NOW)
    assert any("create human task" in a for a in res["actions"])
    task = core.read_task(path)
    assert task.get("unblocked_by") == "H-002"
    human = core.read_task(next((ws / "projects/shop/tasks").glob("H-002-*.md")))
    assert human.owner == "human" and human.get("unblocks") == "A-001"
    assert human.get("due") == "2026-10-11"
    assert "Paste the API key" in human.section("Unblocking action")


def test_blocked_with_missing_unblocker_file_gets_new_task(tmp_path):
    ws = make_ws(tmp_path)
    path = write_task(ws, "A-001", status="blocked", unblocked_by="H-099")
    guard.run_guard(ws, now=NOW)
    assert core.read_task(path).get("unblocked_by") == "H-002"


def test_accepted_decision_creates_executor(tmp_path):
    ws = make_ws(tmp_path)
    write_task(ws, "H-001", type="decision", status="done", decision="accepted",
               closed="2026-10-09", evidence="accepted", executor="web",
               body="\n## For approval\n\nBuild the page with the new price.\n")
    res = guard.run_guard(ws, now=NOW)
    assert any("executor" in a for a in res["actions"])
    created = core.read_task(next((ws / "projects/shop/tasks").glob("A-002-*.md")))
    assert created.owner == "web"
    assert created.get("from_decision") == "H-001"
    assert created.get("due") == "2026-10-11"
    assert "> Build the page with the new price." in created.section("Context")


def test_untrusted_decision_yields_untrusted_executor(tmp_path):
    ws = make_ws(tmp_path)
    write_task(ws, "H-001", type="decision", status="done", decision="accepted",
               closed="2026-10-09", evidence="accepted", source="external",
               body="\n## For approval\n\nText written during an external run.\n")
    guard.run_guard(ws, now=NOW)
    created = core.read_task(next((ws / "projects/shop/tasks").glob("A-002-*.md")))
    assert created.s("source") == "external"


def test_rejected_or_already_executed_decision_is_left_alone(tmp_path):
    ws = make_ws(tmp_path)
    write_task(ws, "H-001", type="decision", status="done", decision="rejected", evidence="x")
    write_task(ws, "H-002", type="decision", status="done", decision="accepted", evidence="x")
    write_task(ws, "A-003", blocked_by="[H-002]")
    res = guard.run_guard(ws, now=NOW)
    assert not any("executor" in a for a in res["actions"])


def test_guard_is_idempotent(tmp_path):
    ws = make_ws(tmp_path)
    write_task(ws, "A-001", status="blocked")
    write_task(ws, "H-002", type="decision", status="done", decision="accepted", evidence="x")
    first = guard.run_guard(ws, now=NOW)
    files = _files(ws)
    contents = {p: p.read_bytes() for p in ws.rglob("*.md")}
    second = guard.run_guard(ws, now=NOW)
    assert first["actions"] and second["actions"] == []
    assert _files(ws) == files
    assert {p: p.read_bytes() for p in ws.rglob("*.md")} == contents


def test_crash_between_create_and_update_does_not_duplicate(tmp_path):
    ws = make_ws(tmp_path)
    path = write_task(ws, "A-001", status="blocked")
    core.create_task(ws, "Unblock A-001", owner="human", project="shop", unblocks="A-001")
    guard.run_guard(ws, now=NOW)
    assert len(list((ws / "projects/shop/tasks").glob("H-*.md"))) == 1
    assert core.read_task(path).get("unblocked_by") == "H-002"


def test_closed_blockers_return_task_to_todo(tmp_path):
    ws = make_ws(tmp_path)
    write_task(ws, "H-001", status="done", evidence="done")
    path = write_task(ws, "A-002", status="blocked", unblocked_by="H-001", blocked_by="[A-003]")
    write_task(ws, "A-003", status="todo")
    guard.run_guard(ws, now=NOW)
    assert core.read_task(path).status == "blocked"
    core.set_status(ws / "projects/shop/tasks/A-003-task.md", "done", evidence="x")
    guard.run_guard(ws, now=NOW)
    assert core.read_task(path).status == "todo"


def test_stale_lock_cleared_and_live_lock_kept(tmp_path):
    ws = make_ws(tmp_path)
    stale = write_task(ws, "A-001", status="in_progress", lock='"2026-10-10T08:00:00|h|1"')
    live = write_task(ws, "A-002", status="in_progress", lock='"2026-10-10T11:30:00|h|1"')
    guard.run_guard(ws, now=NOW)
    assert core.read_task(stale).get("lock") == ""
    assert core.read_task(live).get("lock") == "2026-10-10T11:30:00|h|1"


def test_inbox_blocked_task_without_id(tmp_path):
    ws = make_ws(tmp_path)
    path = write_task(ws, "", project="", status="blocked", title="Ad hoc thing")
    guard.run_guard(ws, now=NOW)
    task = core.read_task(path)
    assert task.get("unblocked_by") == "H-001"
    assert list((ws / "inbox").glob("H-001-*.md"))
    assert guard.run_guard(ws, now=NOW)["actions"] == []


def test_wip_and_evidence_warnings(tmp_path):
    ws = make_ws(tmp_path, wip=2)
    for n in range(1, 4):
        write_task(ws, f"A-00{n}")
    write_task(ws, "A-009", status="done")
    res = guard.run_guard(ws, now=NOW, dry_run=True)
    assert any("WIP 3 over limit 2" in w for w in res["warnings"])
    assert any("A-009: done without evidence" in w for w in res["warnings"])


def test_dry_run_changes_nothing(tmp_path):
    ws = make_ws(tmp_path)
    write_task(ws, "A-001", status="blocked")
    before = {p: p.read_bytes() for p in ws.rglob("*.md")}
    res = guard.run_guard(ws, now=NOW, dry_run=True)
    assert res["actions"]
    assert {p: p.read_bytes() for p in ws.rglob("*.md")} == before


@pytest.mark.skipif(not (DEMO / "agentos.toml").exists(), reason="demo/ not present")
def test_demo_guard_idempotent(tmp_path):
    ws = tmp_path / "demo"
    shutil.copytree(DEMO, ws)
    now = datetime(2026, 10, 11, 9, 0)
    first = guard.run_guard(ws, now=now)
    assert not first["errors"]
    assert not any("executor" in a for a in first["actions"])  # executors exist via blocked_by
    assert guard.run_guard(ws, now=now)["actions"] == []
