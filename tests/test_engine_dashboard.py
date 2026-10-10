import shutil
from datetime import datetime

import pytest

from test_engine_fixtures import DEMO, make_ws, write_task

from agentos import dashboard

NOW = datetime(2026, 10, 10, 12, 0)


def _build(tmp_path):
    ws = make_ws(tmp_path, wip=2)
    write_task(ws, "H-001", type="decision", owner="human", due="2026-10-12",
               title="Decide the price")
    write_task(ws, "H-002", due="2026-10-08", title="Sign the contract")
    write_task(ws, "H-003", due="2026-10-10", title="Call the supplier")
    write_task(ws, "A-004", status="blocked", unblocked_by="H-002")
    write_task(ws, "A-005", status="blocked")
    write_task(ws, "A-006")
    write_task(ws, "A-007", status="done")                  # no evidence
    write_task(ws, "A-008", status="done", evidence="x.md")
    return ws


def test_dashboard_sections(tmp_path):
    ws = _build(tmp_path)
    res = dashboard.generate(ws, now=NOW)
    text = (ws / "projects/dashboard.md").read_text(encoding="utf-8")
    assert res["dashboard_changed"]
    assert "## Decisions waiting for Alex (1)" in text and "H-001 Decide the price" in text
    tasks = text.split("## Tasks for Alex")[1].split("##")[0]
    assert tasks.index("H-002") < tasks.index("H-003")          # overdue first
    assert "**2 day(s) overdue**" in tasks and "**today**" in tasks
    assert "(coffee" not in text
    blocked = text.split("## Blocked")[1].split("##")[0]
    assert "A-004" in blocked and "H-002" in blocked
    assert "A-005" in blocked and "no unblocking human task" in blocked
    assert "| Test shop | active | 3/2 **over limit** |" in text
    assert "## Done without evidence (1)" in text and "A-007" in text
    assert "](shop/tasks/A-004-task.md)" in text  # links relative to projects/


def test_todo_block_preserves_outside_text_and_is_stable(tmp_path):
    ws = _build(tmp_path)
    todo = ws / "TODO.md"
    todo.write_text("# My list\n\n- buy milk\n\n<!-- AGENTOS:START -->\nold\n<!-- AGENTOS:END -->\n\nfooter\n",
                    encoding="utf-8")
    dashboard.generate(ws, now=NOW)
    text = todo.read_text(encoding="utf-8")
    assert text.startswith("# My list\n\n- buy milk\n\n<!-- AGENTOS:START -->")
    assert text.endswith("<!-- AGENTOS:END -->\n\nfooter\n")
    assert "old" not in text and "Sign the contract" in text
    again = dashboard.generate(ws, now=NOW.replace(minute=30))
    assert not again["dashboard_changed"] and not again["todo_changed"]


def test_todo_created_when_missing(tmp_path):
    ws = make_ws(tmp_path)
    dashboard.generate(ws, now=NOW)
    text = (ws / "TODO.md").read_text(encoding="utf-8")
    assert "<!-- AGENTOS:START -->" in text and "nothing waiting for you" in text


@pytest.mark.skipif(not (DEMO / "agentos.toml").exists(), reason="demo/ not present")
def test_demo_dashboard(tmp_path):
    ws = tmp_path / "demo"
    shutil.copytree(DEMO, ws)
    outside = (ws / "TODO.md").read_text(encoding="utf-8").split("<!-- AGENTOS:START -->")[0]
    res = dashboard.generate(ws, now=datetime(2026, 10, 11, 9, 0))
    assert res["errors"] == 0 and res["tasks"] >= 14
    text = (ws / "projects/dashboard.md").read_text(encoding="utf-8")
    assert "## Decisions waiting" in text and "## Blocked" in text
    assert (ws / "TODO.md").read_text(encoding="utf-8").startswith(outside)
