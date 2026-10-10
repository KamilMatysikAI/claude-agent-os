"""Installer: placeholders, never-overwrite, idempotency, profile gate, uninstall.

The OS scheduler is never touched: every test either keeps the queue disabled or replaces
``agentos.scheduler.RUNNER`` with a recorder.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import install  # noqa: E402
from agentos import scheduler  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_scheduler(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        out = "" if argv[:2] != ["crontab", "-l"] else ""
        rc = 1 if "/Query" in argv or argv[:2] == ["launchctl", "print"] else 0
        return subprocess.CompletedProcess(argv, rc, out, "")

    monkeypatch.setattr(scheduler, "RUNNER", fake_run)
    return calls


@pytest.fixture(autouse=True)
def no_real_venv(monkeypatch):
    """The CLI creates .agentos/venv by default; these tests are about files, not pip.
    The real venv install is covered by tests/test_e2e_install.py."""
    seen = []

    def fake_setup(workspace, out=print, pip_args=()):
        seen.append(Path(workspace))
        return {"mode": "skipped", "python": "", "message": "venv skipped in tests"}

    monkeypatch.setattr(install, "setup_engine", fake_setup)
    return seen


@pytest.fixture
def tpl(tmp_path):
    root = tmp_path / "pkg_template"
    (root / ".claude" / "rules").mkdir(parents=True)
    (root / "projects" / ".templates").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("# Constitution for {{owner_name}}\nLang: {{language}}\nTZ: {{ timezone }}\nKeep: {{unknown_key}}\n", encoding="utf-8")
    (root / ".claude" / "rules" / "persona.md").write_text("Name: {{owner_name}}\n", encoding="utf-8")
    (root / "projects" / ".templates" / "PROJECT.md").write_text("---\nslug:\n---\n", encoding="utf-8")
    (root / "logo.bin").write_bytes(b"\x00\x01{{owner_name}}\xff")
    return root


def _answers(ws, **kw):
    ans = dict(install.BASE_DEFAULTS)
    ans.update(owner="Alex", workspace=ws, with_demo=False, full_confirmed=False)
    ans.update(kw)
    return ans


def _snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _run_install(ans, tpl, demo=None, **kw):
    lines = []
    rep = install.install(ans, template_dir=tpl, demo_dir=demo or tpl.parent / "no-demo",
                          run_doctor=False, out=lines.append, **kw)
    return rep, lines


def test_placeholders_filled_and_unknown_kept(tmp_path, tpl):
    ws = tmp_path / "ws"
    _run_install(_answers(ws, language="de", timezone="Europe/Berlin"), tpl)
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Constitution for Alex" in text and "Lang: de" in text and "TZ: Europe/Berlin" in text
    assert "{{unknown_key}}" in text  # left for /setup
    assert (ws / ".claude" / "rules" / "persona.md").read_text(encoding="utf-8") == "Name: Alex\n"
    assert (ws / "logo.bin").read_bytes() == b"\x00\x01{{owner_name}}\xff"  # binary untouched
    for d in ("projects", "inbox/done", "ideas", ".agentos/logs", ".agentos/locks"):
        assert (ws / d).is_dir(), d


def test_config_written_and_valid(tmp_path, tpl):
    ws = tmp_path / "ws"
    _run_install(_answers(ws, owner='A "quoted" name', interval=15, notify="file", panel=True), tpl)
    cfg = tomllib.loads((ws / "agentos.toml").read_text(encoding="utf-8"))
    assert cfg["owner_name"] == 'A "quoted" name'
    assert cfg["queue"] == {**cfg["queue"], "enabled": False, "profile": "safe", "interval_minutes": 15}
    assert cfg["notify"]["kind"] == "file" and cfg["panel"]["enabled"] is True
    from agentos.doctor import validate_config

    assert validate_config(cfg) == []


def test_install_twice_is_idempotent(tmp_path, tpl):
    ws = tmp_path / "ws"
    _run_install(_answers(ws), tpl)
    first = _snapshot(ws)
    rep, _ = _run_install(_answers(ws), tpl)
    assert _snapshot(ws) == first
    assert rep.created == [] and rep.conflicts == []


def test_conflict_writes_new_and_keeps_user_file(tmp_path, tpl):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text("my own rules\n", encoding="utf-8")
    rep, _ = _run_install(_answers(ws), tpl)
    assert (ws / "CLAUDE.md").read_text(encoding="utf-8") == "my own rules\n"
    assert "Constitution for Alex" in (ws / "CLAUDE.md.new").read_text(encoding="utf-8")
    assert [t.name for t, _ in rep.conflicts] == ["CLAUDE.md"]
    snap = _snapshot(ws)
    rep2, _ = _run_install(_answers(ws), tpl)  # still idempotent with a conflict
    assert _snapshot(ws) == snap and len(rep2.conflicts) == 1


def test_changed_answers_go_to_config_new(tmp_path, tpl):
    ws = tmp_path / "ws"
    _run_install(_answers(ws), tpl)
    original = (ws / "agentos.toml").read_text(encoding="utf-8")
    rep, _ = _run_install(_answers(ws, interval=10), tpl)
    assert (ws / "agentos.toml").read_text(encoding="utf-8") == original
    assert "interval_minutes = 10" in (ws / "agentos.toml.new").read_text(encoding="utf-8")


def test_full_profile_requires_confirmation(tmp_path, tpl):
    ws = tmp_path / "ws"
    with pytest.raises(install.InstallError):
        _run_install(_answers(ws, profile="full"), tpl)
    _run_install(_answers(ws, profile="full", full_confirmed=True), tpl)
    assert 'profile = "full"' in (ws / "agentos.toml").read_text(encoding="utf-8")


def test_cli_full_profile_needs_exact_phrase(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "TEMPLATE_DIR", tmp_path / "none")
    ws = tmp_path / "ws"
    base = ["--non-interactive", "--workspace", str(ws), "--owner", "Alex", "--no-doctor", "--profile", "full"]
    assert install.main(base, out=lambda *_: None) == 2
    assert not (ws / "agentos.toml").exists()
    assert install.main(base + ["--confirm-full", "I understand"], out=lambda *_: None) == 0


def test_interactive_wizard_full_needs_typed_phrase(tmp_path, tpl, monkeypatch):
    monkeypatch.setattr(install, "TEMPLATE_DIR", tpl)
    (tpl / ".claude" / "rules-optional").mkdir(parents=True)
    (tpl / ".claude" / "rules-optional" / "web.md").write_text("web rules", encoding="utf-8")
    ws = tmp_path / "ws"
    answers = iter([
        str(ws), "Alex", "en", "UTC",
        "yes",            # queue
        "full", "nope",   # full refused
        "full", "I understand",
        "20",             # interval
        "no", "none",
        "bogus", "web",   # optional rules: unknown re-asked
        "no",
    ])
    rc = install.main(["--no-doctor", "--no-schedule"], input_fn=lambda _p: next(answers), out=lambda *_: None)
    assert rc == 0
    cfg = tomllib.loads((ws / "agentos.toml").read_text(encoding="utf-8"))
    assert cfg["queue"]["profile"] == "full" and cfg["queue"]["enabled"] is True
    assert cfg["queue"]["interval_minutes"] == 20
    assert (ws / ".claude" / "rules" / "web.md").exists()


def test_demo_copied_only_with_flag(tmp_path, tpl):
    demo = tmp_path / "pkg_demo"
    (demo / "projects" / "sample-shop").mkdir(parents=True)
    (demo / "projects" / "sample-shop" / "PROJECT.md").write_text("owner: {{owner_name}}\n", encoding="utf-8")
    (demo / "README.md").write_text("about the demo\n", encoding="utf-8")
    ws1, ws2 = tmp_path / "a", tmp_path / "b"
    _run_install(_answers(ws1), tpl, demo=demo)
    assert not (ws1 / "projects" / "sample-shop").exists()
    _run_install(_answers(ws2, with_demo=True), tpl, demo=demo)
    assert (ws2 / "projects" / "sample-shop" / "PROJECT.md").read_text(encoding="utf-8") == "owner: Alex\n"
    assert not (ws2 / "README.md").exists()


def test_queue_enabled_installs_schedule_via_scheduler(tmp_path, tpl, no_real_scheduler, monkeypatch):
    monkeypatch.setattr(scheduler, "detect_os", lambda *a: "linux")
    ws = tmp_path / "ws"
    _run_install(_answers(ws, queue=True, interval=30), tpl)
    assert ["crontab", "-"] in no_real_scheduler
    assert (ws / ".agentos" / "tick.py").exists()
    assert (ws / ".agentos" / "schedule.json").exists()


def test_print_only_schedule_runs_nothing_mutating(tmp_path, tpl, no_real_scheduler, monkeypatch):
    monkeypatch.setattr(scheduler, "detect_os", lambda *a: "windows")
    ws = tmp_path / "ws"
    _, lines = _run_install(_answers(ws, queue=True), tpl, schedule_print_only=True)
    assert no_real_scheduler == []
    assert any("schtasks" in l and "/Create" in l for l in lines)
    assert not (ws / ".agentos" / "tick.py").exists()


def test_no_schedule_flag_skips_scheduler(tmp_path, tpl, no_real_scheduler):
    ws = tmp_path / "ws"
    rep, _ = _run_install(_answers(ws, queue=True), tpl, schedule=False)
    assert no_real_scheduler == []
    assert any("schedule skipped" in n for n in rep.notes)


def test_uninstall_keeps_user_data(tmp_path, tpl, no_real_scheduler, monkeypatch):
    monkeypatch.setattr(scheduler, "detect_os", lambda *a: "linux")
    ws = tmp_path / "ws"
    _run_install(_answers(ws, queue=True), tpl)
    (ws / "projects" / "mine").mkdir()
    (ws / "projects" / "mine" / "PROJECT.md").write_text("user data\n", encoding="utf-8")
    (ws / ".agentos" / "logs" / "scheduler.log").write_text("log\n", encoding="utf-8")
    before = {k: v for k, v in _snapshot(ws).items() if not k.startswith(".agentos/")}

    install.uninstall(ws, out=lambda *_: None)

    after = {k: v for k, v in _snapshot(ws).items() if not k.startswith(".agentos/")}
    assert after == before
    assert not (ws / ".agentos" / "tick.py").exists()
    assert not (ws / ".agentos" / "install.json").exists()
    assert (ws / ".agentos" / "logs" / "scheduler.log").exists()


def test_uninstall_print_only_changes_nothing(tmp_path, tpl):
    ws = tmp_path / "ws"
    _run_install(_answers(ws), tpl)
    snap = _snapshot(ws)
    install.uninstall(ws, print_only=True, out=lambda *_: None)
    assert _snapshot(ws) == snap


def test_uninstall_refuses_non_workspace(tmp_path):
    with pytest.raises(install.InstallError):
        install.uninstall(tmp_path / "random", out=lambda *_: None)


def test_real_template_installs_cleanly(tmp_path):
    if not install.TEMPLATE_DIR.is_dir() or not any(install.TEMPLATE_DIR.rglob("*")):
        pytest.skip("template/ not written yet")
    ws = tmp_path / "ws"
    args = ["--non-interactive", "--workspace", str(ws), "--owner", "Alex", "--no-doctor"]
    if install.DEMO_DIR.is_dir():
        args.append("--with-demo")
    assert install.main(args, out=lambda *_: None) == 0
    first = _snapshot(ws)
    assert install.main(args, out=lambda *_: None) == 0
    assert _snapshot(ws) == first
    assert not list(ws.rglob("*.new"))
    leftovers = [p for p in ws.rglob("*.md") if "{{owner_name}}" in p.read_text(encoding="utf-8", errors="replace")]
    assert leftovers == []


def test_demo_is_sticky_and_overlays_template(tmp_path, tpl):
    demo = tmp_path / "pkg_demo"
    demo.mkdir()
    (demo / "CLAUDE.md").write_text("demo constitution\n", encoding="utf-8")
    (demo / "agentos.toml").write_text('owner_name = "Demo"\n', encoding="utf-8")
    ws = tmp_path / "ws"
    rep, _ = _run_install(_answers(ws, with_demo=True), tpl, demo=demo)
    assert (ws / "CLAUDE.md").read_text(encoding="utf-8") == "demo constitution\n"
    assert 'owner_name = "Alex"' in (ws / "agentos.toml").read_text(encoding="utf-8")
    assert rep.conflicts == []
    snap = _snapshot(ws)
    rep2, _ = _run_install(_answers(ws, with_demo=False), tpl, demo=demo)  # re-run without the flag
    assert _snapshot(ws) == snap and rep2.conflicts == []


def test_seed_files_edited_later_are_kept_not_conflicts(tmp_path, tpl):
    (tpl / "TODO.md").write_text("# TODO\n<!-- AGENTOS:START -->\n<!-- AGENTOS:END -->\n", encoding="utf-8")
    (tpl / "projects" / "example").mkdir()
    (tpl / "projects" / "example" / "PROJECT.md").write_text("seed\n", encoding="utf-8")
    ws = tmp_path / "ws"
    _run_install(_answers(ws), tpl)
    (ws / "TODO.md").write_text("# TODO\nregenerated by the engine\n", encoding="utf-8")
    (ws / "projects" / "example" / "PROJECT.md").write_text("edited by an agent\n", encoding="utf-8")
    (ws / "projects" / ".templates" / "PROJECT.md").write_text("user changed the template\n", encoding="utf-8")
    rep, _ = _run_install(_answers(ws), tpl)
    assert {p.name for p in rep.kept} == {"TODO.md", "PROJECT.md"}
    assert [t.parent.name for t, _ in rep.conflicts] == [".templates"]  # real template drift is reported
    assert not (ws / "TODO.md.new").exists()


def test_optional_rules_only_when_chosen(tmp_path, tpl):
    opt = tpl / ".claude" / "rules-optional"
    opt.mkdir(parents=True)
    (opt / "web.md").write_text("web rules for {{owner_name}}\n", encoding="utf-8")
    (opt / "sales.md").write_text("sales rules\n", encoding="utf-8")
    ws1, ws2 = tmp_path / "a", tmp_path / "b"
    _run_install(_answers(ws1), tpl)
    assert not (ws1 / ".claude" / "rules-optional").exists()
    assert not (ws1 / ".claude" / "rules" / "web.md").exists()
    _run_install(_answers(ws2, rules="web, sales.md"), tpl)
    assert (ws2 / ".claude" / "rules" / "web.md").read_text(encoding="utf-8") == "web rules for Alex\n"
    assert (ws2 / ".claude" / "rules" / "sales.md").exists()
    assert not (ws2 / ".claude" / "rules-optional").exists()
    with pytest.raises(install.InstallError):
        _run_install(_answers(tmp_path / "c", rules="nope"), tpl)


def test_notes_dirs_created_and_archive_runtime_never_copied(tmp_path, tpl):
    (tpl / ".claude" / "rules-archive").mkdir(parents=True)
    (tpl / ".claude" / "rules-archive" / "old.md").write_text("old rule\n", encoding="utf-8")
    (tpl / ".agentos" / "tmp").mkdir(parents=True)
    (tpl / ".agentos" / "tmp" / "scratch.txt").write_text("x\n", encoding="utf-8")
    ws = tmp_path / "ws"
    _run_install(_answers(ws), tpl)
    assert (ws / "notes" / "sessions").is_dir()
    assert not (ws / ".claude" / "rules-archive" / "old.md").exists()
    assert not (ws / ".agentos" / "tmp" / "scratch.txt").exists()
    assert ".agentos/" in (ws / ".gitignore").read_text(encoding="utf-8")  # covers .agentos/tmp/


def test_uninstall_removes_only_a_real_engine_venv(tmp_path, tpl):
    ws = tmp_path / "ws"
    _run_install(_answers(ws), tpl)
    venv = ws / ".agentos" / "venv"
    (venv / "lib").mkdir(parents=True)
    (venv / "lib" / "x.py").write_text("", encoding="utf-8")
    install.uninstall(ws, print_only=True, out=lambda *_: None)
    assert venv.is_dir()                                  # print-only changes nothing
    install.uninstall(ws, out=lambda *_: None)
    assert venv.is_dir()                                  # no pyvenv.cfg: not ours, kept
    (venv / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    install.uninstall(ws, out=lambda *_: None)
    assert not venv.exists() and (ws / "agentos.toml").exists()


def test_engine_placeholder_follows_the_venv(tmp_path, tpl):
    ws = tmp_path / "ws"
    assert install.engine_placeholder(ws) == "python -P -m agentos"
    from agentos import env as engine_env
    exe = engine_env.venv_python(ws)
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    assert install.engine_placeholder(ws).startswith(".agentos/venv/")
    assert install.engine_placeholder(ws).endswith(" -P -m agentos")
