from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional

from .config import Profile
from .util import CmdResult, ensure_dir, require_cmd


def _run(cmd: List[str], cwd: Optional[Path] = None, timeout_s: Optional[int] = None) -> CmdResult:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return CmdResult(proc.returncode, proc.stdout, proc.stderr)


def _ssh_base_args(profile: Profile) -> List[str]:
    args = ["ssh", "-p", str(profile.port)]
    if profile.identity_file:
        args += ["-i", profile.identity_file]
    # Avoid interactive host key prompts if you want. Default is safer to allow prompt once.
    # args += ["-o", "StrictHostKeyChecking=accept-new"]
    return args


def _scp_base_args(profile: Profile) -> List[str]:
    args = ["scp", "-P", str(profile.port), "-r"]
    if profile.identity_file:
        args += ["-i", profile.identity_file]
    return args


def _remote(profile: Profile) -> str:
    return f"{profile.user}@{profile.host}"


def test_ssh(profile: Profile) -> CmdResult:
    require_cmd("ssh")
    cmd = _ssh_base_args(profile) + [_remote(profile), "echo", "SSH_OK"]
    return _run(cmd, timeout_s=20)


def ensure_remote_dir(profile: Profile, remote_dir: str) -> CmdResult:
    require_cmd("ssh")
    cmd = _ssh_base_args(profile) + [_remote(profile), "mkdir", "-p", shlex.quote(remote_dir)]
    # Note: remote shell quoting: we pass a single argument, so keep it simple:
    cmd = _ssh_base_args(profile) + [_remote(profile), f"mkdir -p {shlex.quote(remote_dir)}"]
    return _run(cmd, timeout_s=30)


def push(profile: Profile, local_path: str, remote_path: str) -> CmdResult:
    """
    Copy local -> remote.
    local_path can be a file or folder.
    remote_path is a folder or file destination.
    """
    require_cmd("scp")
    if profile.ensure_remote_dir:
        # If remote_path looks like a directory, ensure it exists.
        # We assume user gives a directory path for remote_path.
        ensure_remote_dir(profile, remote_path)

    src = Path(local_path).expanduser()
    if not src.exists():
        return CmdResult(2, "", f"Local path not found: {src}")

    cmd = _scp_base_args(profile) + [str(src), f"{_remote(profile)}:{remote_path}"]
    return _run(cmd, timeout_s=None)


def pull(profile: Profile, remote_path: str, local_path: str) -> CmdResult:
    """
    Copy remote -> local.
    remote_path can be a file or folder.
    local_path is destination folder/path.
    """
    require_cmd("scp")
    dst = Path(local_path).expanduser()
    ensure_dir(dst if dst.suffix == "" else dst.parent)

    cmd = _scp_base_args(profile) + [f"{_remote(profile)}:{remote_path}", str(dst)]
    return _run(cmd, timeout_s=None)


def generate_keypair(key_path: Path, comment: str = "parasync") -> CmdResult:
    require_cmd("ssh-keygen")
    key_path = key_path.expanduser()
    ensure_dir(key_path.parent)
    cmd = ["ssh-keygen", "-t", "ed25519", "-C", comment, "-f", str(key_path)]
    return _run(cmd, timeout_s=None)


def install_pubkey(profile: Profile, pubkey_path: Path) -> CmdResult:
    """
    Adds pubkey to remote ~/.ssh/authorized_keys using ssh.
    This is the cross-platform replacement for ssh-copy-id.
    """
    require_cmd("ssh")
    pubkey_path = pubkey_path.expanduser()
    if not pubkey_path.exists():
        return CmdResult(2, "", f"Public key not found: {pubkey_path}")

    pubkey = pubkey_path.read_text(encoding="utf-8").strip()
    # Remote: mkdir ~/.ssh; append key; set perms
    remote_cmd = (
        "mkdir -p ~/.ssh && "
        "chmod 700 ~/.ssh && "
        f"echo {shlex.quote(pubkey)} >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys && "
        "echo KEY_INSTALLED"
    )
    cmd = _ssh_base_args(profile) + [_remote(profile), remote_cmd]
    return _run(cmd, timeout_s=60)
