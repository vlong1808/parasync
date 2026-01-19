from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from .util import default_config_path, ensure_dir


@dataclass
class Profile:
    name: str
    host: str
    user: str
    port: int = 22
    # Local/remote paths for push/pull. You can set both and choose direction at runtime.
    local_path: str = ""
    remote_path: str = ""
    # Optional: extra ssh options
    identity_file: str = ""   # path to private key
    # If true, creates remote_path automatically before transfer
    ensure_remote_dir: bool = True


@dataclass
class AppConfig:
    profiles: List[Profile]


def config_file(path: Optional[Path] = None) -> Path:
    return path or default_config_path()


def load_config(path: Optional[Path] = None) -> AppConfig:
    p = config_file(path)
    if not p.exists():
        return AppConfig(profiles=[])
    raw = json.loads(p.read_text(encoding="utf-8"))
    profiles = [Profile(**item) for item in raw.get("profiles", [])]
    return AppConfig(profiles=profiles)


def save_config(cfg: AppConfig, path: Optional[Path] = None) -> Path:
    p = config_file(path)
    ensure_dir(p.parent)
    raw = {"profiles": [asdict(prof) for prof in cfg.profiles]}
    p.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return p


def upsert_profile(cfg: AppConfig, prof: Profile) -> None:
    for i, existing in enumerate(cfg.profiles):
        if existing.name == prof.name:
            cfg.profiles[i] = prof
            return
    cfg.profiles.append(prof)


def delete_profile(cfg: AppConfig, name: str) -> bool:
    before = len(cfg.profiles)
    cfg.profiles = [p for p in cfg.profiles if p.name != name]
    return len(cfg.profiles) != before


def get_profile(cfg: AppConfig, name: str) -> Optional[Profile]:
    for p in cfg.profiles:
        if p.name == name:
            return p
    return None
