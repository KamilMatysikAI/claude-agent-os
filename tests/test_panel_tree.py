"""Dependency tree: chains from blocked_by / unblocked_by, shared children, cycles, lanes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentos import core  # noqa: E402
from panel import data  # noqa: E402
from test_panel_helpers import build_workspace  # noqa: E402


def _ids(node):
    return {"id": node["id"], "ref": node.get("ref", False), "cycle": node.get("cycle", False),
            "children": [_ids(c) for c in node["children"]]}


def test_chains_follow_blocked_by_and_unblocked_by(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    tree = data.dependency_tree(ws, "coffee-shop")
    chains = [_ids(c) for c in tree["chains"]]
    assert chains[0]["id"] == "H-003"                      # human blocker first (it unblocks)
    a003 = chains[0]["children"][0]
    assert a003["id"] == "A-003" and not a003["ref"]
    assert a003["children"][0]["id"] == "A-004"
    a002 = next(c for c in chains if c["id"] == "A-002")
    shared = a002["children"][0]
    assert shared["id"] == "A-003" and shared["ref"] is True and shared["children"] == []
    assert tree["linked"] == 4 and tree["open"] == 10


def test_unlinked_tasks_go_to_lanes(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    tree = data.dependency_tree(ws, "coffee-shop")
    lanes = {l["lane"]: [t["id"] for t in l["tasks"]] for l in tree["lanes"]}
    assert lanes["you"][0] == "H-004"                       # overdue first
    assert set(lanes["you"]) == {"H-001", "H-002", "H-004", "A-005"}
    assert lanes["web"] == ["A-008"] and lanes["copy"] == ["A-009"]
    assert list(lanes)[0] == "you"
    flat = str(tree)
    assert "A-010" not in flat and "A-006" not in flat      # archived / closed stay out


def test_cycle_is_cut_not_recursed(tmp_path):
    root = build_workspace(tmp_path / "ws")
    a = core.create_task(root, "Loop one", owner="soft", project="newsletter")
    b = core.create_task(root, "Loop two", owner="soft", project="newsletter")
    for task, other in ((a, b), (b, a)):
        t = core.read_task(task.path)
        t.meta["blocked_by"] = [other.id]
        core.write_task_atomic(t)
    ws = data.Workspace(root)
    tree = data.dependency_tree(ws, "newsletter")
    ids = [_ids(c) for c in tree["chains"]]
    loop = next(c for c in ids if c["id"] in (a.id, b.id))
    assert loop["children"][0]["children"][0]["cycle"] is True


def test_closed_blocker_is_a_satisfied_edge(tmp_path):
    root = build_workspace(tmp_path / "ws")
    path = next((root / "projects" / "newsletter" / "tasks").glob("H-002-*.md"))
    core.set_status(path, "done", evidence="exported")
    ws = data.Workspace(root)
    tree = data.dependency_tree(ws, "newsletter")
    # H-002 is done, so A-002 no longer waits on anything open: no chain, own lane
    assert tree["chains"] == []
    lanes = {l["lane"]: [t["id"] for t in l["tasks"]] for l in tree["lanes"]}
    assert lanes["copy"] == ["A-002"]


def test_tree_payload_covers_all_projects(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    payload = data.tree_payload(ws)
    slugs = [p["slug"] for p in payload["projects"]]
    assert slugs == ["coffee-shop", "newsletter"]           # most linked first
    assert payload["projects"][1]["chains"][0]["id"] == "H-002"


def test_project_payload_embeds_tree(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    p = data.project_payload(ws, "coffee-shop")
    assert p["tree"]["chains"][0]["id"] == "H-003"
    assert data.project_payload(ws, "../coffee-shop") is None


def test_valid_key():
    assert data.valid_key("coffee-shop/A-001")
    assert data.valid_key("inbox/check-broken-links")
    for bad in ("../x", "coffee-shop/../A-001", "coffee-shop/a-001", "a/b/c", "/A-001",
                "coffee-shop/A-001.md", "inbox/..", "Coffee/A-001", ""):
        assert not data.valid_key(bad), bad
