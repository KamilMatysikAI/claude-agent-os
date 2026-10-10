"""Doctor checks on a freshly installed workspace (no real CLI or scheduler needed)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import install  # noqa: E402
from agentos import doctor  # noqa: E402


def _ws(tmp_path, **cfg):
    ws = tmp_path / "ws"
    ans = dict(install.BASE_DEFAULTS, owner="Alex", workspace=ws, with_demo=False, full_confirmed=False)
    ans.update(cfg)
    install.install(ans, template_dir=tmp_path / "none", demo_dir=tmp_path / "none",
                    schedule=False, run_doctor=False, out=lambda *_: None)
    (ws / ".claude").mkdir(exist_ok=True)
    return ws


def _runner(argv, **kw):
    return subprocess.CompletedProcess(argv, 0, "9.9.9 (Claude Code)\n", "")


def _checks(ws, which=lambda name: None, installed=False):
    return {c.name: c for c in doctor.run_checks(
        ws, which=which, runner=_runner,
        schedule_status=lambda w: {"installed": installed, "name": "job", "backend": "cron", "state": {}})}


def test_missing_claude_fails(tmp_path):
    checks = _checks(_ws(tmp_path))
    assert checks["claude"].level == "fail"
    assert checks["python"].level == "ok"
    assert checks["workspace"].level == "ok"
    assert checks["gitleaks"].level == "info"


def test_claude_found_reports_version(tmp_path):
    checks = _checks(_ws(tmp_path), which=lambda n: "/bin/" + n if n == "claude" else None)
    assert checks["claude"].level == "ok" and "9.9.9" in checks["claude"].message


def test_queue_enabled_without_schedule_warns(tmp_path):
    checks = _checks(_ws(tmp_path, queue=True))
    assert checks["schedule"].level == "warn"


def test_invalid_config_fails(tmp_path):
    ws = _ws(tmp_path)
    cfg = ws / "agentos.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('profile = "safe"', 'profile = "root"'), encoding="utf-8")
    assert _checks(ws)["workspace"].level == "fail"


def test_no_workspace(tmp_path):
    names = {c.name: c.level for c in doctor.run_checks(tmp_path / "nope", which=lambda n: None, runner=_runner)}
    assert names["workspace"] == "fail"


def test_banned_words_warning(tmp_path):
    ws = _ws(tmp_path)
    (ws / ".agentos" / "banned_words.txt").write_text("# mine\nAcme Secret\n", encoding="utf-8")
    (ws / ".claude" / "rules").mkdir(parents=True, exist_ok=True)
    (ws / ".claude" / "rules" / "x.md").write_text("Working for acme-secret today\n", encoding="utf-8")
    assert _checks(ws)["banned words"].level == "warn"


def test_render_and_exit_code(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    out = doctor.render(doctor.run_checks(ws, which=lambda n: None, runner=_runner,
                                          schedule_status=lambda w: {"installed": False}))
    assert "[FAIL] claude" in out.replace("  ", " ") or "FAIL" in out
