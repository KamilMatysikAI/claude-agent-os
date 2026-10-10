"""Where the engine lives: the workspace's own virtual environment and packaged data.

`install.py` creates `<workspace>/.agentos/venv` and installs this package into it with a
normal (not editable) `pip install`. Every generated command (scheduled job, panel run-now,
the skills via CLAUDE.md, the README) runs `<venv python> -P -m agentos`:

* the venv sits under `.agentos/`, which every queue profile denies to `Edit`;
* `-P` keeps the current directory (the agent-writable workspace) off `sys.path`, so a
  planted `<workspace>/agentos/` can never shadow the installed package.

Offline fallback: when pip cannot build the package, the installer links the cloned repo
into the venv with a `.pth` file instead. The commands stay the same.

No side effects at import time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

VENV_DIR = Path(".agentos") / "venv"
LINK_FILE = "claude-agent-os-repo.pth"   # offline fallback written by install.py
HERE = Path(__file__).resolve().parent


def venv_dir(workspace) -> Path:
    return Path(workspace) / VENV_DIR


def venv_python(workspace, windowed: bool = False, os_name: str | None = None) -> Path:
    """The venv interpreter. `windowed` picks pythonw.exe on Windows (no console window)."""
    windows = (os_name or ("windows" if os.name == "nt" else "posix")) == "windows"
    base = venv_dir(workspace)
    if windows:
        return base / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
    return base / "bin" / "python"


def has_venv(workspace) -> bool:
    return venv_python(workspace).is_file()


def engine_python(workspace, windowed: bool = False) -> str:
    """Interpreter for engine subprocesses: the workspace venv if present, else this one."""
    if has_venv(workspace):
        exe = venv_python(workspace, windowed=windowed)
        if exe.is_file():
            return str(exe)
        return str(venv_python(workspace))
    return sys.executable


def engine_command(os_name: str | None = None, venv: bool = True) -> str:
    """The command the docs and skills use, relative to the workspace root."""
    if not venv:
        return "python -P -m agentos"
    windows = (os_name or ("windows" if os.name == "nt" else "posix")) == "windows"
    exe = ".agentos/venv/Scripts/python" if windows else ".agentos/venv/bin/python"
    return f"{exe} -P -m agentos"


def is_source_checkout() -> bool:
    """True when running from the cloned repo (not from an installed copy)."""
    return (HERE.parent / "pyproject.toml").is_file() and (HERE.parent / "profiles").is_dir()


def package_root() -> Path:
    """Folder that holds `agentos/` and `panel/` (repo root, or site-packages)."""
    return HERE.parent


def data_path(installed: str, source: str) -> Path:
    """A packaged data file: `installed` is relative to the agentos package in an installed
    copy, `source` relative to the repo root in a checkout."""
    candidate = HERE / installed
    return candidate if candidate.exists() else HERE.parent / source


def profiles_dir() -> Path:
    return data_path("profiles", "profiles")
