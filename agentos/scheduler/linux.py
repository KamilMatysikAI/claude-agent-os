"""Linux backends: user crontab (default) or a systemd --user timer.

The crontab backend rewrites only the lines tagged with our marker; every other line of the
user's crontab is preserved byte for byte.
"""
from __future__ import annotations

import shlex
from pathlib import Path
from typing import Optional

from . import (
    PRODUCT_NAME,
    RemoveFile,
    Run,
    ScheduleSpec,
    SchedulerError,
    WriteFile,
    assert_own_name,
    run_cmd,
)


def cron_expression(minutes: int) -> str:
    if minutes < 60:
        return f"*/{minutes} * * * *"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"0 */{hours} * * *" if hours < 24 else "0 0 * * *"
    raise SchedulerError("cron supports intervals below 60 minutes or whole hours (60, 120, ...)")


def _cron_quote(value: str) -> str:
    # '%' means newline in a crontab command - escape it.
    return shlex.quote(str(value)).replace("%", "\\%")


class CronBackend:
    kind = "cron"

    @staticmethod
    def name(job_id: str) -> str:
        return f"{PRODUCT_NAME}:{job_id}"

    def marker(self, job_id: str) -> str:
        return f"# {self.name(job_id)}"

    def cron_line(self, spec: ScheduleSpec) -> str:
        cmd = f"{_cron_quote(spec.python)} {_cron_quote(str(spec.launcher))} >/dev/null 2>&1"
        return f"{cron_expression(spec.interval_minutes)} {cmd} {self.marker(spec.job_id)}"

    @staticmethod
    def current() -> str:
        res = run_cmd(["crontab", "-l"])
        # exit != 0 with "no crontab for user" simply means empty
        return res.stdout if res.returncode == 0 and res.stdout else ""

    def _without_ours(self, text: str, job_id: str) -> list:
        mark = self.marker(job_id)
        return [line for line in text.splitlines() if not line.rstrip().endswith(mark)]

    def install_plan(self, spec: ScheduleSpec) -> list:
        assert_own_name(self.name(spec.job_id))
        current = self.current()
        lines = self._without_ours(current, spec.job_id) + [self.cron_line(spec)]
        new = "\n".join(lines) + "\n"
        if new == current:
            return []
        return [Run(["crontab", "-"], input=new)]

    def remove_plan(self, job_id: str, workspace: Path) -> list:
        assert_own_name(self.name(job_id))
        current = self.current()
        lines = self._without_ours(current, job_id)
        if len(lines) == len(current.splitlines()):
            return []
        new = ("\n".join(lines) + "\n") if lines else ""
        return [Run(["crontab", "-"], input=new)]

    def status(self, job_id: str, workspace: Path) -> dict:
        mark = self.marker(job_id)
        lines = [l for l in self.current().splitlines() if l.rstrip().endswith(mark)]
        return {"installed": bool(lines), "name": self.name(job_id), "backend": self.kind,
                "detail": lines[0] if lines else ""}


class SystemdBackend:
    kind = "systemd"

    def __init__(self, unit_dir: Optional[Path] = None):
        self.unit_dir = unit_dir or Path.home() / ".config" / "systemd" / "user"

    @staticmethod
    def name(job_id: str) -> str:
        return f"{PRODUCT_NAME}-{job_id}"

    def units(self, job_id: str):
        base = self.unit_dir / self.name(job_id)
        return base.with_suffix(".service"), base.with_suffix(".timer")

    def install_plan(self, spec: ScheduleSpec) -> list:
        name = self.name(spec.job_id)
        assert_own_name(name)
        service, timer = self.units(spec.job_id)
        service_txt = (
            "[Unit]\n"
            f"Description={PRODUCT_NAME} queue tick\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"WorkingDirectory={spec.workspace}\n"
            f"ExecStart={shlex.quote(spec.python)} {shlex.quote(str(spec.launcher))}\n"
        )
        timer_txt = (
            "[Unit]\n"
            f"Description={PRODUCT_NAME} queue timer\n\n"
            "[Timer]\n"
            "OnBootSec=5min\n"
            f"OnUnitActiveSec={spec.interval_minutes}min\n"
            f"Unit={service.name}\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )
        return [
            WriteFile(service, service_txt),
            WriteFile(timer, timer_txt),
            Run(["systemctl", "--user", "daemon-reload"]),
            Run(["systemctl", "--user", "enable", "--now", timer.name]),
        ]

    def remove_plan(self, job_id: str, workspace: Path) -> list:
        assert_own_name(self.name(job_id))
        service, timer = self.units(job_id)
        if not service.exists() and not timer.exists():
            return []
        return [
            Run(["systemctl", "--user", "disable", "--now", timer.name], ignore_errors=True),
            RemoveFile(timer),
            RemoveFile(service),
            Run(["systemctl", "--user", "daemon-reload"], ignore_errors=True),
        ]

    def status(self, job_id: str, workspace: Path) -> dict:
        name = self.name(job_id)
        assert_own_name(name)
        res = run_cmd(["systemctl", "--user", "is-active", f"{name}.timer"])
        active = res.returncode == 0
        return {"installed": active, "name": name, "backend": self.kind,
                "detail": (res.stdout or "").strip()}
