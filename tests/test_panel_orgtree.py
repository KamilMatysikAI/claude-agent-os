"""Organisation tree (/api/orgtree), message codes for translation, and the Polish demo."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentos import core, guard  # noqa: E402
from panel import actions, data  # noqa: E402
from test_panel_helpers import build_workspace  # noqa: E402

DEMO_PL = ROOT / "demo-pl"
DEMO_EN = ROOT / "demo"


def _leaves(node):
    if node["kind"] == "task":
        return [node]
    return [leaf for c in node["children"] for leaf in _leaves(c)]


def test_tree_has_every_open_task_once(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    tree = data.org_tree_payload(ws)
    leaves = _leaves(tree["root"])
    keys = [leaf["key"] for leaf in leaves]
    assert len(keys) == len(set(keys))
    expected = {e.key for e in ws.scan() if not e.archived and e.task.status in core.OPEN_STATUSES}
    assert set(keys) == expected
    assert "coffee-shop/A-006" not in keys and "coffee-shop/A-010" not in keys  # closed, archived


def test_tree_counts_add_up(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    tree = data.org_tree_payload(ws)
    root = tree["root"]
    for field in ("open", "in_progress", "blocked", "overdue", "mine"):
        assert root[field] == sum(p[field] for p in root["children"]), field
        for p in root["children"]:
            assert p[field] == sum(r[field] for r in p["children"]), (p["slug"], field)
    assert root["open"] == len(_leaves(root)) == tree["stats"]["open"]
    assert tree["stats"]["projects"] == sum(1 for p in root["children"] if not p["inbox"])
    assert root["name"] == "Alex"


def test_tree_roles_and_order(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    root = data.org_tree_payload(ws)["root"]
    coffee = next(p for p in root["children"] if p["slug"] == "coffee-shop")
    roles = [r["role"] for r in coffee["children"]]
    assert roles == sorted(roles, key=data.ROLE_ORDER.index)
    human = next(r for r in coffee["children"] if r["role"] == "human")
    assert all(t["human"] for t in human["children"]) and human["mine"] == human["open"]
    # the inbox is its own branch, always last
    assert root["children"][-1]["inbox"] is True and root["children"][-1]["slug"] == ""
    # hot projects first: the order keys never increase
    projects = [p for p in root["children"] if not p["inbox"]]
    order = [(-p["in_progress"], -p["blocked"], -p["open"]) for p in projects]
    assert order == sorted(order)


def test_task_nodes_in_a_role_sorted_by_heat(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    root = data.org_tree_payload(ws)["root"]
    for p in root["children"]:
        for r in p["children"]:
            keys = [data._org_task_sort(t) for t in r["children"]]
            assert keys == sorted(keys)


def test_action_errors_carry_a_translation_code(tmp_path):
    ws = data.Workspace(build_workspace(tmp_path / "ws"))
    with pytest.raises(actions.ActionError) as exc:
        actions.validate(ws, "done", "coffee-shop/H-001", {})
    assert exc.value.code == "evidence_required"
    assert exc.value.public()["code"] == "evidence_required"
    with pytest.raises(actions.ActionError) as exc:
        actions.validate(ws, "run-now", "coffee-shop/H-001", {})
    assert exc.value.code == "run_human"
    entry = ws.find("coffee-shop/H-001")
    assert data.run_now_block(entry)[0] == "run_human"
    assert data.run_now_block_reason(entry).startswith("This is your task")


def test_phase_words_in_polish():
    plan = "# Plan\n\n## Faza 1: badanie\n\nFaza zamknięta.\n\n## Faza 2: sprzedaż (bieżąca)\n\nZadania: A-001, A-002.\n"
    out = data._plan_phase(plan, {"A-001": "done", "A-002": "todo"})
    assert [p["title"] for p in out["phases"]] == ["Faza 1: badanie", "Faza 2: sprzedaż"]
    assert out["current"]["title"] == "Faza 2: sprzedaż"
    assert (out["current"]["done"], out["current"]["open"]) == (1, 1)


# ── demo in Polish ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not (DEMO_PL / "agentos.toml").exists(), reason="demo-pl/ not present")
def test_demo_pl_is_rich_and_clean(tmp_path):
    ws_root = tmp_path / "demo-pl"
    shutil.copytree(DEMO_PL, ws_root)
    ws = data.Workspace(ws_root)
    assert data.meta_payload(ws)["language"] == "pl"
    tree = data.org_tree_payload(ws)
    assert not tree["errors"]
    assert tree["stats"]["projects"] == 8
    assert tree["stats"]["open"] >= 60 and tree["stats"]["roles"] >= 6
    assert data.decisions_payload(ws)["count"] == 8
    assert len(ws.scan()) == 85                       # 83 project tasks + 2 in the inbox
    for path in DEMO_PL.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert "—" not in text and "–" not in text, path


@pytest.mark.skipif(not (DEMO_PL / "agentos.toml").exists(), reason="demo-pl/ not present")
def test_demo_pl_guard_idempotent(tmp_path):
    ws = tmp_path / "demo-pl"
    shutil.copytree(DEMO_PL, ws)
    before = {p: p.read_bytes() for p in ws.rglob("*.md")}
    now = datetime(2026, 10, 11, 9, 0)
    first = guard.run_guard(ws, now=now)
    assert not first["errors"]
    assert first["actions"] == []
    assert {p: p.read_bytes() for p in ws.rglob("*.md")} == before


def test_installer_picks_the_demo_by_language():
    import importlib.util
    spec = importlib.util.spec_from_file_location("install_mod", ROOT / "install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.demo_dir_for("pl") == DEMO_PL
    assert mod.demo_dir_for("pl-PL") == DEMO_PL
    assert mod.demo_dir_for("en") == DEMO_EN
    assert mod.demo_dir_for("de") == DEMO_EN
