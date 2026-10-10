"""Panel HTTP API: every endpoint, security gates, actions, undo window, run-now."""

from __future__ import annotations

import gzip
import http.client
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentos import core  # noqa: E402
from panel import server as panel_server  # noqa: E402
from test_panel_helpers import build_workspace, workspace_copy  # noqa: E402

UNDO = 0.4


class Client:
    def __init__(self, port: int):
        self.port = port

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, body=data, headers=hdrs)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        if res.getheader("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return res, raw

    def get(self, path, **kw):
        res, raw = self.request("GET", path, **kw)
        try:
            return res.status, json.loads(raw)
        except ValueError:
            return res.status, raw

    def post(self, path, body, **kw):
        res, raw = self.request("POST", path, body=body, **kw)
        return res.status, json.loads(raw)


def _start(ws: Path):
    spawned: list = []

    def fake_spawn(workspace, task_path):
        spawned.append((Path(workspace), Path(task_path)))
        return True, ""

    httpd = panel_server.make_server(ws, "127.0.0.1", 0, undo_seconds=UNDO, spawn=fake_spawn)
    panel_server.run_in_thread(httpd)
    return httpd, spawned


@pytest.fixture
def env(tmp_path):
    ws = build_workspace(tmp_path / "ws")
    httpd, spawned = _start(ws)
    client = Client(httpd.server_address[1])
    yield {"ws": ws, "c": client, "spawned": spawned, "httpd": httpd}
    httpd.shutdown()
    httpd.panel_state.pending.flush()
    httpd.server_close()


def task_file(ws: Path, project: str, ident: str) -> Path:
    return next((ws / "projects" / project / "tasks").glob(f"{ident}-*.md"))


def wait_applied(c: Client, pid: str, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        status, item = c.get(f"/api/pending/{pid}")
        if item["status"] not in ("pending", "applying"):
            return item
        time.sleep(0.05)
    raise AssertionError("pending action was never applied")


# ── read endpoints ───────────────────────────────────────────────────────────

def test_static_files(env):
    c = env["c"]
    for path, ctype in (("/", "text/html"), ("/app.js", "javascript"), ("/styles.css", "text/css"),
                        ("/favicon.svg", "image/svg")):
        res, raw = c.request("GET", path)
        assert res.status == 200, path
        assert ctype in res.getheader("Content-Type")
        assert raw
    res, _ = c.request("GET", "/")
    assert "frame-ancestors 'none'" in res.getheader("Content-Security-Policy")
    for bad in ("/server.py", "/static/../server.py", "/../agentos.toml", "/static/app.js"):
        res, _ = c.request("GET", bad)
        assert res.status == 404, bad


def test_meta_uses_config(env):
    status, meta = env["c"].get("/api/meta")
    assert status == 200
    assert meta["owner_name"] == "Alex"
    assert meta["language"] == "en"
    assert meta["product"]


def test_today_payload(env):
    status, t = env["c"].get("/api/today")
    assert status == 200
    assert t["decisions"]["count"] == 3
    assert t["decisions"]["overdue"] == 1
    assert t["decisions"]["top"][0]["key"] == "coffee-shop/H-001"   # overdue first
    today = [s["key"] for s in t["mine"]["today"]]
    assert today == ["coffee-shop/H-003"]
    assert t["mine"]["today"][0]["unblocks"] == 1
    assert [s["key"] for s in t["mine"]["overdue"]] == ["coffee-shop/H-004"]
    assert [s["key"] for s in t["review"]] == ["coffee-shop/A-005"]
    waiting = t["waiting"]
    assert [s["key"] for s in waiting] == ["coffee-shop/A-003"]
    assert waiting[0]["unblocked_by_key"] == "coffee-shop/H-003"
    assert "logo" in waiting[0]["unblocking_action"]
    assert t["agents_working"] == 1
    # archived and closed tasks never appear on Today
    flat = json.dumps(t)
    assert "A-010" not in flat


def test_decisions_payload(env):
    status, d = env["c"].get("/api/decisions")
    assert status == 200
    keys = [s["key"] for s in d["items"]]
    assert keys[0] == "coffee-shop/H-001"
    assert set(keys) == {"coffee-shop/H-001", "coffee-shop/H-002", "newsletter/H-001"}
    first = d["items"][0]
    assert "option B" in first["recommendation"]
    assert first["links"] and first["links"][0]["label"] == "survey notes"


def test_projects_and_project(env):
    c = env["c"]
    status, p = c.get("/api/projects")
    assert status == 200
    rows = {r["slug"]: r for r in p["items"]}
    assert rows["coffee-shop"]["name"] == "Corner coffee shop launch"
    assert rows["coffee-shop"]["blocked"] == 1
    assert rows["coffee-shop"]["wip"] == 5 and rows["coffee-shop"]["wip_limit"] == 5
    assert rows["newsletter"]["health"] == 3
    assert p["inbox_open"] == 1
    status, one = c.get("/api/project/coffee-shop")
    assert status == 200
    assert "100 pickup orders" in one["goal"]
    assert one["phase"]["current"]["title"].startswith("Phase 2")
    assert one["log"][0]["text"] == "Web started the menu page."
    assert [b["key"] for b in one["blockers"]] == ["coffee-shop/A-003"]
    assert one["blockers"][0]["unblocked_by_key"] == "coffee-shop/H-003"
    assert {s["key"] for s in one["recent_closed"]} == {
        "coffee-shop/A-001", "coffee-shop/A-006", "coffee-shop/A-007"}
    assert c.get("/api/project/nope")[0] == 404


def test_activity(env):
    c = env["c"]
    status, a = c.get("/api/activity")
    assert status == 200
    kinds = {i["key"]: i["kind"] for g in a["groups"] for i in g["items"]}
    assert kinds["coffee-shop/A-006"] == "agent"
    assert kinds["coffee-shop/A-007"] == "cancelled"
    assert "coffee-shop/A-001" not in kinds          # older than 24 h
    assert [w["key"] for w in a["working"]] == ["coffee-shop/A-002"]
    status, week = c.get("/api/activity?since=2026-01-01T00:00")
    assert week["clamped"] is True                   # archive needs archive=1
    status, full = c.get("/api/activity?since=2000-01-01&archive=1")
    assert full["clamped"] is False
    every = {i["key"] for g in full["groups"] for i in g["items"]}
    assert "coffee-shop/A-010" in every              # archived task on demand


def test_tasks_scopes(env):
    c = env["c"]
    _, open_ = c.get("/api/tasks?scope=open")
    _, recent = c.get("/api/tasks?scope=recent")
    _, all_ = c.get("/api/tasks?scope=all")
    keys = lambda p: {s["key"] for s in p["items"]}  # noqa: E731
    assert "coffee-shop/A-006" not in keys(open_)
    assert "coffee-shop/A-006" in keys(recent)
    assert "coffee-shop/A-010" not in keys(recent)
    assert "coffee-shop/A-010" in keys(all_)
    assert "inbox/check-broken-links" in keys(open_)
    assert c.get("/api/tasks?scope=everything")[0] == 400


def test_task_detail(env):
    c = env["c"]
    status, t = c.get("/api/task/coffee-shop/A-003")
    assert status == 200
    assert t["status"] == "blocked"
    assert t["blocked_by"] == ["A-002"] and t["unblocked_by"] == "H-003"
    assert t["waiting_on_this"] == ["coffee-shop/A-004"]
    assert t["actions"]["run_now"] is False and "blocked" in t["run_now_reason"]
    assert t["rel_path"].startswith("projects/coffee-shop/tasks/")
    status, inbox = c.get("/api/task/inbox/check-broken-links")
    assert status == 200 and inbox["actions"]["run_now"] is True
    status, arch = c.get("/api/task/coffee-shop/A-010")
    assert arch["archived"] is True
    assert not any(arch["actions"].values())


def test_gzip_only_for_large_payloads(tmp_path):
    ws = build_workspace(tmp_path / "ws")
    for n in range(90):
        core.create_task(ws, f"Generated task number {n} with a reasonably long title",
                         owner="copy", project="coffee-shop")
    httpd, _ = _start(ws)
    try:
        c = Client(httpd.server_address[1])
        res, raw = c.request("GET", "/api/tasks?scope=all", headers={"Accept-Encoding": "gzip"})
        assert res.status == 200
        assert res.getheader("Content-Encoding") == "gzip"
        assert len(json.loads(raw)["items"]) > 90
        res, _ = c.request("GET", "/api/meta", headers={"Accept-Encoding": "gzip"})
        assert res.getheader("Content-Encoding") is None
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── security gates ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/task/..%2F..%2Fagentos.toml",
    "/api/task/coffee-shop/..%2F..%2F..%2Fagentos.toml",
    "/api/task/coffee-shop%2F..%2F..%2Fagentos.toml",
    "/api/task/../../agentos.toml",
    "/api/task/coffee-shop/A-003/../../../../agentos.toml",
    "/api/task/inbox/..%5C..%5Cagentos.toml",
    "/api/task/C:%5Cwindows%5Cwin.ini",
    "/api/task/%2Fetc%2Fpasswd",
    "/api/project/..%2F..",
    "/api/project/../../agentos.toml",
])
def test_path_traversal_rejected(env, path):
    res, raw = env["c"].request("GET", path)
    assert res.status in (400, 404)
    assert b"owner_name" not in raw and b"[panel]" not in raw


def test_traversal_in_action_key_rejected(env):
    status, body = env["c"].post("/api/actions", {"action": "note", "key": "../../agentos.toml",
                                                  "note": "x"})
    assert status == 404
    status, body = env["c"].post("/api/actions", {"action": "note",
                                                  "key": "coffee-shop/../../agentos", "note": "x"})
    assert status == 404
    assert "x" not in (env["ws"] / "agentos.toml").read_text(encoding="utf-8").split("\n")[-1]


def test_foreign_host_refused(env):
    res, _ = env["c"].request("GET", "/api/today", headers={"Host": "attacker.example"})
    assert res.status == 403
    res, _ = env["c"].request("POST", "/api/actions", body={}, headers={"Host": "attacker.example"})
    assert res.status == 403


def test_post_needs_json_same_origin(env):
    c = env["c"]
    res, _ = c.request("POST", "/api/actions", headers={"Content-Type": "text/plain"})
    assert res.status == 415
    status, _ = c.post("/api/actions", {"action": "note", "key": "coffee-shop/A-008", "note": "x"},
                       headers={"Origin": "http://attacker.example"})
    assert status == 403


# ── actions ──────────────────────────────────────────────────────────────────

def test_decide_writes_decision_status_and_note(env):
    c, ws = env["c"], env["ws"]
    path = task_file(ws, "coffee-shop", "H-001")
    status, body = c.post("/api/actions", {"action": "decide", "key": "coffee-shop/H-001",
                                           "accepted": True, "note": "Go with B, start Monday."})
    assert status == 202
    pid = body["pending"]["id"]
    # inside the undo window: file untouched, decision hidden from the stack
    assert "decision: accepted" not in path.read_text(encoding="utf-8")
    _, d = c.get("/api/decisions")
    assert "coffee-shop/H-001" not in [s["key"] for s in d["items"]]
    assert wait_applied(c, pid)["status"] == "applied"
    task = core.read_task(path)
    assert task.meta["decision"] == "accepted"
    assert task.meta["status"] == "done"
    assert task.meta["closed"]
    assert task.meta["evidence"]
    assert "Go with B, start Monday." in task.section("Owner notes")
    # shows up in activity as a decision
    _, a = c.get("/api/activity")
    kinds = {i["key"]: (i["kind"], i["decision"]) for g in a["groups"] for i in g["items"]}
    assert kinds["coffee-shop/H-001"] == ("decided", "accepted")


def test_reject_decision(env):
    c, ws = env["c"], env["ws"]
    status, body = c.post("/api/actions", {"action": "decide", "key": "newsletter/H-001",
                                           "accepted": False, "note": "Tuesday works better"})
    assert status == 202
    wait_applied(c, body["pending"]["id"])
    task = core.read_task(task_file(ws, "newsletter", "H-001"))
    assert task.meta["decision"] == "rejected" and task.meta["status"] == "done"
    assert "[rejected] Tuesday works better" in task.section("Owner notes")


def test_undo_window(env):
    c, ws = env["c"], env["ws"]
    path = task_file(ws, "coffee-shop", "H-002")
    before = path.read_text(encoding="utf-8")
    status, body = c.post("/api/actions", {"action": "decide", "key": "coffee-shop/H-002",
                                           "accepted": True})
    pid = body["pending"]["id"]
    status, undone = c.post("/api/undo", {"id": pid})
    assert status == 200 and undone["status"] == "undone"
    time.sleep(UNDO * 2)
    assert path.read_text(encoding="utf-8") == before
    _, d = c.get("/api/decisions")
    assert "coffee-shop/H-002" in [s["key"] for s in d["items"]]
    # too late: once applied, undo is refused
    status, body = c.post("/api/actions", {"action": "decide", "key": "coffee-shop/H-002",
                                           "accepted": True})
    wait_applied(c, body["pending"]["id"])
    status, late = c.post("/api/undo", {"id": body["pending"]["id"]})
    assert status == 409
    assert c.post("/api/undo", {"id": "nope"})[0] == 404


def test_second_action_inside_window_refused(env):
    c = env["c"]
    c.post("/api/actions", {"action": "cancel", "key": "coffee-shop/A-008"})
    status, body = c.post("/api/actions", {"action": "done", "key": "coffee-shop/A-008",
                                           "evidence": "x"})
    assert status == 409


def test_done_requires_evidence(env):
    c, ws = env["c"], env["ws"]
    status, body = c.post("/api/actions", {"action": "done", "key": "coffee-shop/H-003"})
    assert status == 400 and "evidence" in body["error"].lower()
    status, body = c.post("/api/actions", {"action": "done", "key": "coffee-shop/H-003",
                                           "evidence": "projects/coffee-shop/materials/logo.svg",
                                           "note": "sent both files"})
    assert status == 202
    wait_applied(c, body["pending"]["id"])
    task = core.read_task(task_file(ws, "coffee-shop", "H-003"))
    assert task.meta["status"] == "done"
    assert task.meta["evidence"] == "projects/coffee-shop/materials/logo.svg"
    assert "sent both files" in task.section("Owner notes")


def test_cancel(env):
    c, ws = env["c"], env["ws"]
    status, body = c.post("/api/actions", {"action": "cancel", "key": "coffee-shop/A-008",
                                           "note": "not needed"})
    assert status == 202
    wait_applied(c, body["pending"]["id"])
    task = core.read_task(task_file(ws, "coffee-shop", "A-008"))
    assert task.meta["status"] == "cancelled" and task.meta["closed"]


def test_wrong_action_for_type(env):
    c = env["c"]
    status, body = c.post("/api/actions", {"action": "decide", "key": "coffee-shop/A-008",
                                           "accepted": True})
    assert status == 400 and "not a decision" in body["error"]
    status, body = c.post("/api/actions", {"action": "done", "key": "coffee-shop/H-001",
                                           "evidence": "x"})
    assert status == 400
    status, body = c.post("/api/actions", {"action": "decide", "key": "coffee-shop/H-001",
                                           "accepted": "yes"})
    assert status == 400
    status, body = c.post("/api/actions", {"action": "explode", "key": "coffee-shop/H-001"})
    assert status == 400
    status, body = c.post("/api/actions", {"action": "done", "key": "coffee-shop/A-006",
                                           "evidence": "x"})
    assert status == 400 and "already done" in body["error"]


def test_archived_task_is_read_only(env):
    c = env["c"]
    for payload in ({"action": "note", "note": "hi"}, {"action": "done", "evidence": "x"},
                    {"action": "run-now"}, {"action": "cancel"}):
        status, body = c.post("/api/actions", {**payload, "key": "coffee-shop/A-010"})
        assert status == 400 and "archived" in body["error"]


def test_note_and_edit(env):
    c, ws = env["c"], env["ws"]
    status, body = c.post("/api/actions", {"action": "note", "key": "coffee-shop/A-008",
                                           "note": "Keep the sitemap simple."})
    assert status == 200
    path = task_file(ws, "coffee-shop", "A-008")
    assert "Keep the sitemap simple." in core.read_task(path).section("Owner notes")
    assert c.post("/api/actions", {"action": "note", "key": "coffee-shop/A-008",
                                   "note": "  "})[0] == 400
    # stale edit refused
    status, body = c.post("/api/actions", {"action": "edit", "key": "coffee-shop/A-008",
                                           "mtime_ns": "1", "title": "New"})
    assert status == 409
    _, t = c.get("/api/task/coffee-shop/A-008")
    status, body = c.post("/api/actions", {"action": "edit", "key": "coffee-shop/A-008",
                                           "mtime_ns": t["mtime_ns"], "title": "SEO basics v2",
                                           "priority": "high", "due": "2026-12-01"})
    assert status == 200
    task = core.read_task(path)
    assert task.meta["title"] == "SEO basics v2"
    assert task.meta["priority"] == "high" and task.meta["due"] == "2026-12-01"
    assert task.meta["id"] == "A-008" and task.meta["owner"] == "web"
    assert "Keep the sitemap simple." in task.section("Owner notes")   # body untouched
    _, t = c.get("/api/task/coffee-shop/A-008")
    assert c.post("/api/actions", {"action": "edit", "key": "coffee-shop/A-008",
                                   "mtime_ns": t["mtime_ns"], "due": "soon"})[0] == 400
    assert c.post("/api/actions", {"action": "edit", "key": "coffee-shop/A-008",
                                   "mtime_ns": t["mtime_ns"], "title": "two\nlines"})[0] == 400


def test_run_now_rejected_for_human_ask_blocked_and_running(env):
    c = env["c"]
    cases = {
        "coffee-shop/H-003": "your task",          # human task
        "coffee-shop/H-001": "",                   # decision (human) — any reason
        "coffee-shop/A-009": "autonomy: ask",
        "coffee-shop/A-003": "status: todo",       # blocked
        "coffee-shop/A-002": "",                   # in progress with a live lock
    }
    for key, fragment in cases.items():
        status, body = c.post("/api/actions", {"action": "run-now", "key": key})
        assert status == 400, key
        assert fragment.lower() in body["error"].lower(), (key, body)
    assert env["spawned"] == []
    assert not (env["ws"] / ".agentos" / "run-now.json").exists()


def test_run_now_writes_request_and_spawns_once(env):
    c, ws = env["c"], env["ws"]
    status, body = c.post("/api/actions", {"action": "run-now", "key": "coffee-shop/A-008"})
    assert status == 200 and body["started"] is True
    requests = json.loads((ws / ".agentos" / "run-now.json").read_text(encoding="utf-8"))
    assert requests[0]["path"] == "projects/coffee-shop/tasks/A-008-seo-basics.md"
    assert requests[0]["who"] == "panel"
    assert len(env["spawned"]) == 1
    assert env["spawned"][0][1].name == "A-008-seo-basics.md"
    assert "run requested from the panel" in core.read_task(
        task_file(ws, "coffee-shop", "A-008")).section("Progress log")
    status, again = c.post("/api/actions", {"action": "run-now", "key": "coffee-shop/A-008"})
    assert status == 200 and again["started"] is False and "already" in again["message"]
    assert len(env["spawned"]) == 1


def test_spawn_runner_builds_detached_command(monkeypatch, tmp_path):
    from panel import actions
    seen = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw

    monkeypatch.setattr(actions.subprocess, "Popen", FakePopen)
    ok, detail = actions.spawn_runner(tmp_path, tmp_path / "projects" / "p" / "tasks" / "t.md")
    assert ok, detail
    assert seen["cmd"][1:6] == ["-P", "-m", "agentos", "run", "--task"]
    assert seen["cmd"][6] == "projects/p/tasks/t.md"
    assert "--workspace" in seen["cmd"]
    assert seen["kw"]["stdin"] is actions.subprocess.DEVNULL
    assert ("creationflags" in seen["kw"]) or seen["kw"].get("start_new_session") is True
    assert "shell" not in seen["kw"]


def test_create_task_and_idea(env):
    c, ws = env["c"], env["ws"]
    status, body = c.post("/api/create", {"kind": "task", "title": "Call the printer",
                                          "project": "coffee-shop", "owner": "human",
                                          "priority": "high", "due": "2026-12-24"})
    assert status == 201 and body["id"].startswith("H-")
    assert body["key"] == f"coffee-shop/{body['id']}"
    task = core.read_task(task_file(ws, "coffee-shop", body["id"]))
    assert task.meta["source"] == "panel" and task.meta["owner"] == "human"
    assert task.meta["due"] == "2026-12-24"
    status, body = c.get(f"/api/task/{body['key']}")
    assert status == 200
    status, body = c.post("/api/create", {"kind": "task", "title": "Check image sizes",
                                          "owner": "web", "details": "Report only."})
    assert status == 201 and body["key"].startswith("inbox/")
    assert c.get(f"/api/task/{body['key']}")[0] == 200
    status, body = c.post("/api/create", {"kind": "idea", "title": "Loyalty card",
                                          "details": "Stamp card, 10th coffee free"})
    assert status == 201
    ideas = list((ws / "ideas").glob("*loyalty-card.md"))
    assert len(ideas) == 1 and "10th coffee" in ideas[0].read_text(encoding="utf-8")
    assert c.post("/api/create", {"kind": "task", "title": "x", "project": "../evil"})[0] == 400
    assert c.post("/api/create", {"kind": "task", "title": "x", "owner": "root"})[0] == 400
    assert c.post("/api/create", {"kind": "task", "title": ""})[0] == 400
    assert c.post("/api/create", {"kind": "spell", "title": "x"})[0] == 400
    assert not (ws.parent / "evil").exists()


def test_flush_applies_pending_on_shutdown(tmp_path):
    ws = build_workspace(tmp_path / "ws")
    httpd = panel_server.make_server(ws, "127.0.0.1", 0, undo_seconds=60)
    panel_server.run_in_thread(httpd)
    try:
        c = Client(httpd.server_address[1])
        status, body = c.post("/api/actions", {"action": "cancel", "key": "coffee-shop/A-008"})
        assert status == 202
    finally:
        httpd.shutdown()
        httpd.panel_state.pending.flush()
        httpd.server_close()
    task = core.read_task(task_file(ws, "coffee-shop", "A-008"))
    assert task.meta["status"] == "cancelled"


def test_failed_apply_is_reported(env):
    c, ws = env["c"], env["ws"]
    status, body = c.post("/api/actions", {"action": "cancel", "key": "coffee-shop/A-008"})
    # someone closes the task in the meantime
    path = task_file(ws, "coffee-shop", "A-008")
    core.set_status(path, "done", evidence="closed by hand")
    item = wait_applied(c, body["pending"]["id"])
    assert item["status"] == "failed" and "meantime" in item["error"]
    assert core.read_task(path).meta["status"] == "done"


def test_every_endpoint_on_demo_copy(tmp_path):
    """Smoke test on a copy of demo/ (falls back to the fixture while demo is incomplete)."""
    ws = workspace_copy(tmp_path)
    httpd, _ = _start(ws)
    try:
        c = Client(httpd.server_address[1])
        for path in ("/api/meta", "/api/today", "/api/decisions", "/api/projects", "/api/tree",
                     "/api/activity", "/api/activity?since=2000-01-01&archive=1",
                     "/api/tasks?scope=open", "/api/tasks?scope=recent", "/api/tasks?scope=all"):
            status, _ = c.get(path)
            assert status == 200, path
        _, projects = c.get("/api/projects")
        for p in projects["items"]:
            assert c.get(f"/api/project/{p['slug']}")[0] == 200
        _, tasks = c.get("/api/tasks?scope=all")
        for s in tasks["items"][:200]:
            assert c.get(f"/api/task/{s['key']}")[0] == 200, s["key"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_idea_uses_the_add_idea_template(env):
    """Ideas from the panel follow ideas/.templates/idea.md, like the add-idea skill."""
    c, ws = env["c"], env["ws"]
    status, body = c.post("/api/create", {"kind": "idea", "title": "Gift box: 3 origins",
                                          "details": "A one-off box for the holidays"})
    assert status == 201
    path = ws / "ideas" / "gift-box-3-origins.md"
    assert body["message"].endswith("ideas/gift-box-3-origins.md.")
    text = path.read_text(encoding="utf-8")
    fm = text.split("---")[1]
    assert 'title: "Gift box: 3 origins"' in fm
    for field in ("status: new", "category: other", "potential: medium", "effort: medium",
                  "tags: []", "project:"):
        assert field in fm, field
    assert "created: 20" in fm
    assert "YYYY-MM-DD" not in text and "Idea name" not in text
    assert "# Gift box: 3 origins" in text
    what = text.split("## What it is", 1)[1].split("##", 1)[0]
    assert "A one-off box for the holidays" in what and "<!--" not in what
    assert "added from the panel" in text.split("## Notes", 1)[1]
    # same title again: a new file with -2, the first one untouched
    status, body = c.post("/api/create", {"kind": "idea", "title": "Gift box: 3 origins"})
    assert status == 201 and (ws / "ideas" / "gift-box-3-origins-2.md").exists()
    assert path.read_text(encoding="utf-8") == text
    # the generated index lists both
    index = (ws / "ideas" / "index.md").read_text(encoding="utf-8")
    assert "gift-box-3-origins.md" in index and "gift-box-3-origins-2.md" in index


def test_idea_falls_back_to_the_packaged_template(env):
    c, ws = env["c"], env["ws"]
    tpl = ws / "ideas" / ".templates" / "idea.md"
    if tpl.exists():
        tpl.rename(tpl.with_name("idea.md.off"))
    status, _ = c.post("/api/create", {"kind": "idea", "title": "Cold brew cans"})
    assert status == 201
    text = (ws / "ideas" / "cold-brew-cans.md").read_text(encoding="utf-8")
    assert "potential: medium" in text and "## Problem it solves" in text
