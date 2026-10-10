"""Scheduler backends build the right commands per OS. Every external command is mocked."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentos import scheduler  # noqa: E402
from agentos.scheduler import Run, RemoveFile, WriteFile, linux, macos, windows  # noqa: E402


class FakeRunner:
    """Records commands; simulates crontab and query results."""

    def __init__(self, crontab: str = "", installed: bool = False):
        self.calls = []
        self.crontab = crontab
        self.installed = installed

    def __call__(self, argv, input=None, **kwargs):
        self.calls.append((list(argv), input))
        if argv[:2] == ["crontab", "-l"]:
            return subprocess.CompletedProcess(argv, 0 if self.crontab else 1, self.crontab, "no crontab")
        if argv[:2] == ["crontab", "-"]:
            self.crontab = input
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["schtasks", "/Query"] or argv[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(argv, 0 if self.installed else 1, "Status: Ready\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def argvs(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def fake(monkeypatch):
    f = FakeRunner()
    monkeypatch.setattr(scheduler, "RUNNER", f)
    return f


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "My Workspace"
    w.mkdir()
    (w / "agentos.toml").write_text('owner_name = "Alex"\nlanguage = "en"\n[queue]\nenabled = true\ninterval_minutes = 30\n', encoding="utf-8")
    return w


def spec(ws, minutes=30, python="/usr/bin/python3"):
    return scheduler.make_spec(ws, minutes, "linux", python=python)


# --------------------------------------------------------------------- common
def test_job_id_is_stable_and_safe(ws):
    a, b = scheduler.job_id(ws), scheduler.job_id(ws)
    assert a == b and a.startswith("my-workspace-") and " " not in a


def test_interval_validation():
    for bad in (0, -5, 1440, "x"):
        with pytest.raises(scheduler.SchedulerError):
            scheduler.validate_interval(bad)


def test_foreign_names_are_refused():
    with pytest.raises(scheduler.SchedulerError):
        scheduler.assert_own_name("Some Other Task")
    scheduler.assert_own_name(scheduler.PRODUCT_NAME + " - x")


def test_launcher_runs_run_then_dashboard(ws):
    src = scheduler.launcher_source(ws)
    compile(src, "tick.py", "exec")
    assert src.index('["run"]') < src.index('["dashboard"]')
    assert repr(str(ws.resolve())) in src and "CREATE_NO_WINDOW" in src
    # -P keeps the agent-writable workspace (cwd) off sys.path: no shadow `agentos` package
    assert '[sys.executable, "-P", "-m", "agentos"]' in src


# --------------------------------------------------------------------- windows
def test_windows_install_uses_pythonw_and_prefix(ws, fake):
    scheduler.install(ws, 30, os_name="windows", python=r"X:\py\pythonw.exe", out=lambda *_: None)
    create = [a for a in fake.argvs() if a[:2] == ["schtasks", "/Create"]]
    assert len(create) == 1
    argv = create[0]
    assert argv[argv.index("/TN") + 1].startswith(scheduler.PRODUCT_NAME + " - ")
    assert argv[argv.index("/SC") + 1] == "MINUTE" and argv[argv.index("/MO") + 1] == "30"
    tr = argv[argv.index("/TR") + 1]
    assert "pythonw.exe" in tr and tr.endswith('tick.py"') and "/F" in argv
    assert (ws / ".agentos" / "tick.py").exists()


def test_windows_tr_too_long_raises(tmp_path):
    long_ws = tmp_path / ("x" * 200)
    s = scheduler.make_spec(long_ws, 30, "windows", python="C:/" + "p" * 80 + "/pythonw.exe")
    with pytest.raises(scheduler.SchedulerError):
        windows.Backend().install_plan(s)


def test_windows_remove_only_when_present(ws, fake):
    scheduler.remove(ws, os_name="windows", out=lambda *_: None)
    assert not any(a[:2] == ["schtasks", "/Delete"] for a in fake.argvs())
    fake.installed = True
    scheduler.remove(ws, os_name="windows", out=lambda *_: None)
    delete = [a for a in fake.argvs() if a[:2] == ["schtasks", "/Delete"]]
    assert delete and delete[0][3].startswith(scheduler.PRODUCT_NAME)


def test_windows_status(ws, fake):
    assert scheduler.status(ws, os_name="windows")["installed"] is False
    fake.installed = True
    st = scheduler.status(ws, os_name="windows")
    assert st["installed"] is True and st["backend"] == "schtasks"


def test_print_only_runs_nothing(ws, fake):
    lines = []
    scheduler.install(ws, 30, os_name="windows", python="pythonw.exe", print_only=True, out=lines.append)
    assert fake.calls == []
    assert not (ws / ".agentos" / "tick.py").exists()
    assert any("schtasks" in l for l in lines)


# --------------------------------------------------------------------- macOS
def test_macos_plan(ws, tmp_path):
    be = macos.Backend(uid=501, agents_dir=tmp_path / "LaunchAgents")
    s = scheduler.make_spec(ws, 15, "macos", python="/usr/bin/python3")
    plan = be.install_plan(s)
    write = plan[0]
    assert isinstance(write, WriteFile) and write.path.name.startswith("com." + scheduler.PRODUCT_NAME)
    data = plistlib.loads(write.content)
    assert data["StartInterval"] == 900 and data["ProgramArguments"][1].endswith("tick.py")
    assert data["Label"] == be.name(s.job_id)
    runs = [a.argv for a in plan if isinstance(a, Run)]
    assert runs[-1] == ["launchctl", "bootstrap", "gui/501", str(write.path)]
    assert plan[1].ignore_errors  # bootout before re-bootstrap


def test_macos_remove_and_status(ws, tmp_path, fake):
    be = macos.Backend(uid=501, agents_dir=tmp_path / "LaunchAgents")
    jid = scheduler.job_id(ws)
    be.plist_path(jid).parent.mkdir(parents=True)
    be.plist_path(jid).write_bytes(b"x")
    plan = be.remove_plan(jid, ws)
    assert plan[0].argv[:2] == ["launchctl", "bootout"] and isinstance(plan[1], RemoveFile)
    assert be.status(jid, ws)["installed"] is False
    assert fake.argvs()[-1] == ["launchctl", "print", f"gui/501/{be.name(jid)}"]


# --------------------------------------------------------------------- Linux cron
OTHER = "0 3 * * * /usr/local/bin/backup.sh # nightly\n@reboot echo hi\n"


def test_cron_expression():
    assert linux.cron_expression(15) == "*/15 * * * *"
    assert linux.cron_expression(120) == "0 */2 * * *"
    with pytest.raises(scheduler.SchedulerError):
        linux.cron_expression(90)


def test_cron_install_preserves_other_lines_and_is_idempotent(ws, fake):
    fake.crontab = OTHER
    scheduler.install(ws, 30, os_name="linux", python="/usr/bin/python3", out=lambda *_: None)
    assert fake.crontab.startswith(OTHER)
    ours = [l for l in fake.crontab.splitlines() if "# " + scheduler.PRODUCT_NAME + ":" in l]
    assert len(ours) == 1 and ours[0].startswith("*/30 * * * * ") and "tick.py" in ours[0]
    writes_before = sum(1 for a in fake.argvs() if a == ["crontab", "-"])
    scheduler.install(ws, 30, os_name="linux", python="/usr/bin/python3", out=lambda *_: None)
    assert sum(1 for a in fake.argvs() if a == ["crontab", "-"]) == writes_before  # nothing to change
    scheduler.install(ws, 10, os_name="linux", python="/usr/bin/python3", out=lambda *_: None)
    ours = [l for l in fake.crontab.splitlines() if scheduler.PRODUCT_NAME in l]
    assert len(ours) == 1 and ours[0].startswith("*/10 ")
    assert scheduler.status(ws, os_name="linux")["installed"] is True


def test_cron_remove_keeps_other_lines(ws, fake):
    fake.crontab = OTHER
    scheduler.install(ws, 30, os_name="linux", python="/usr/bin/python3", out=lambda *_: None)
    scheduler.remove(ws, os_name="linux", out=lambda *_: None)
    assert fake.crontab == OTHER
    n = len(fake.calls)
    scheduler.remove(ws, os_name="linux", out=lambda *_: None)  # second remove = no write
    assert not any(c[0] == ["crontab", "-"] for c in fake.calls[n:])


def test_cron_quotes_paths_with_spaces_and_percent(tmp_path):
    w = tmp_path / "a 100% dir"
    w.mkdir()
    line = linux.CronBackend().cron_line(scheduler.make_spec(w, 5, "linux", python="/opt/py 3/python"))
    assert "'/opt/py 3/python'" in line and "\\%" in line


# --------------------------------------------------------------------- Linux systemd
def test_systemd_plan(ws, tmp_path):
    be = linux.SystemdBackend(unit_dir=tmp_path / "units")
    s = spec(ws, 20)
    plan = be.install_plan(s)
    files = {a.path.suffix: a.content for a in plan if isinstance(a, WriteFile)}
    assert "OnUnitActiveSec=20min" in files[".timer"] and "tick.py" in files[".service"]
    runs = [a.argv for a in plan if isinstance(a, Run)]
    assert runs[-1][:4] == ["systemctl", "--user", "enable", "--now"]
    assert runs[-1][4].startswith(scheduler.PRODUCT_NAME) and runs[-1][4].endswith(".timer")


# --------------------------------------------------------------------- CLI
def test_cli_status_and_print_only(ws, fake, monkeypatch, capsys):
    monkeypatch.setattr(scheduler, "detect_os", lambda *a: "linux")
    assert scheduler.main(["status", "--workspace", str(ws)]) == 0
    assert "not installed" in capsys.readouterr().out
    assert scheduler.main(["install", "--workspace", str(ws), "--print-only"]) == 0
    assert not any(c[0] == ["crontab", "-"] for c in fake.calls)


def _fake_venv(ws: Path, os_name: str) -> Path:
    from agentos import env as engine_env
    for windowed in (False, True):
        exe = engine_env.venv_python(ws, windowed=windowed, os_name=os_name)
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("", encoding="utf-8")
    return engine_env.venv_python(ws, windowed=True, os_name=os_name)


def test_job_uses_the_workspace_venv_without_pythonpath(ws):
    os_name = "windows" if os.name == "nt" else "linux"
    src = scheduler.launcher_source(ws)
    assert "USE_PYTHONPATH = True" in src            # no venv yet: fallback
    exe = _fake_venv(ws, os_name)
    spec = scheduler.make_spec(ws, 30, os_name)
    assert spec.python == str(exe)
    src = scheduler.launcher_source(ws)
    assert "USE_PYTHONPATH = False" in src and '"-P", "-m", "agentos"' in src
