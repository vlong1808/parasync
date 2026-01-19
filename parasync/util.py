from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def is_windows() -> bool:
    return platform.system().lower().startswith("win")


def home_dir() -> Path:
    return Path.home()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def require_cmd(cmd: str) -> None:
    if which(cmd) is None:
        raise RuntimeError(f"Required command not found in PATH: {cmd}")


def default_config_dir() -> Path:
    # Keep it simple and local to the user
    return home_dir() / ".parasync"


def default_config_path() -> Path:
    return default_config_dir() / "config.json"


@dataclass(frozen=True)
class CmdResult:
    returncode: int
    stdout: str
    stderr: str


def mask_secret(s: str) -> str:
    # Basic masking for logs if you ever add passwords (you should not).
    return s.replace(os.environ.get("USER", ""), "<USER>")
