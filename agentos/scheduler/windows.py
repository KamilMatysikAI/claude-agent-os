"""Windows backend: Task Scheduler via schtasks.

The job runs ``pythonw.exe <workspace>/.agentos/tick.py`` - pythonw has no console, so no
window pops up every N minutes (no VBS/PowerShell wrapper needed). Without ``/RU`` the task
runs as the current user, only while the user is logged on, with limited rights.
"""
from __future__ import annotations

from pathlib import Path

from . import PRODUCT_NAME, Run, ScheduleSpec, SchedulerError, assert_own_name, run_cmd

TR_MAX = 261  # schtasks limit for the /TR value


class Backend:
    kind = "schtasks"

    @staticmethod
    def name(job_id: str) -> str:
        return f"{PRODUCT_NAME} - {job_id}"

    @staticmethod
    def task_command(spec: ScheduleSpec) -> str:
        tr = f'"{spec.python}" "{spec.launcher}"'
        if len(tr) > TR_MAX:
            raise SchedulerError(
                f"task command is {len(tr)} characters (schtasks limit {TR_MAX}); "
                "move the workspace or the Python install to a shorter path"
            )
        return tr

    def install_plan(self, spec: ScheduleSpec) -> list:
        name = self.name(spec.job_id)
        assert_own_name(name)
        # /F replaces our own task with the same name, which makes install idempotent.
        return [
            Run(
                [
                    "schtasks", "/Create",
                    "/TN", name,
                    "/SC", "MINUTE",
                    "/MO", str(spec.interval_minutes),
                    "/TR", self.task_command(spec),
                    "/F",
                ]
            )
        ]

    def remove_plan(self, job_id: str, workspace: Path) -> list:
        name = self.name(job_id)
        assert_own_name(name)
        if not self.status(job_id, workspace)["installed"]:
            return []
        return [Run(["schtasks", "/Delete", "/TN", name, "/F"])]

    def status(self, job_id: str, workspace: Path) -> dict:
        name = self.name(job_id)
        assert_own_name(name)
        res = run_cmd(["schtasks", "/Query", "/TN", name, "/FO", "LIST"])
        detail = ""
        if res.returncode == 0:
            keep = ("Next Run Time", "Status")
            detail = "\n".join(l.strip() for l in (res.stdout or "").splitlines() if l.strip().startswith(keep))
        return {"installed": res.returncode == 0, "name": name, "backend": self.kind, "detail": detail}
