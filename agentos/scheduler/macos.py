"""macOS backend: a per-user launchd agent in ~/Library/LaunchAgents."""
from __future__ import annotations

import os
import plistlib
from pathlib import Path
from typing import Optional

from . import PRODUCT_NAME, RemoveFile, Run, ScheduleSpec, WriteFile, assert_own_name, run_cmd


class Backend:
    kind = "launchd"

    def __init__(self, uid: Optional[int] = None, agents_dir: Optional[Path] = None):
        self.uid = uid if uid is not None else (os.getuid() if hasattr(os, "getuid") else 501)
        self.agents_dir = agents_dir or Path.home() / "Library" / "LaunchAgents"

    @staticmethod
    def name(job_id: str) -> str:
        return f"com.{PRODUCT_NAME}.{job_id}"

    def plist_path(self, job_id: str) -> Path:
        return self.agents_dir / f"{self.name(job_id)}.plist"

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    def plist_bytes(self, spec: ScheduleSpec) -> bytes:
        logs = spec.workspace / ".agentos" / "logs"
        data = {
            "Label": self.name(spec.job_id),
            "ProgramArguments": [spec.python, str(spec.launcher)],
            "StartInterval": spec.interval_minutes * 60,
            "RunAtLoad": False,
            "WorkingDirectory": str(spec.workspace),
            "StandardOutPath": str(logs / "launchd.out.log"),
            "StandardErrorPath": str(logs / "launchd.err.log"),
            "ProcessType": "Background",
        }
        return plistlib.dumps(data)

    def install_plan(self, spec: ScheduleSpec) -> list:
        name = self.name(spec.job_id)
        assert_own_name(name)
        plist = self.plist_path(spec.job_id)
        return [
            WriteFile(plist, self.plist_bytes(spec)),
            # bootout first so a re-install picks up the new plist (error = not loaded, fine)
            Run(["launchctl", "bootout", self.domain, str(plist)], ignore_errors=True),
            Run(["launchctl", "bootstrap", self.domain, str(plist)]),
        ]

    def remove_plan(self, job_id: str, workspace: Path) -> list:
        name = self.name(job_id)
        assert_own_name(name)
        plist = self.plist_path(job_id)
        plan: list = [Run(["launchctl", "bootout", self.domain, str(plist)], ignore_errors=True)]
        if plist.exists():
            plan.append(RemoveFile(plist))
        return plan

    def status(self, job_id: str, workspace: Path) -> dict:
        name = self.name(job_id)
        assert_own_name(name)
        res = run_cmd(["launchctl", "print", f"{self.domain}/{name}"])
        return {
            "installed": res.returncode == 0,
            "name": name,
            "backend": self.kind,
            "detail": "" if res.returncode == 0 or not self.plist_path(job_id).exists()
            else "plist present but not loaded",
        }
