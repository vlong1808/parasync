from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from .config import AppConfig, Profile, delete_profile, get_profile, load_config, save_config, upsert_profile
from .core import generate_keypair, install_pubkey, pull, push, test_ssh
from .util import default_config_path


def _print_result(rc: int, out: str, err: str) -> int:
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, end="" if err.endswith("\n") else "\n")
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="parasync", description="Push/pull files between Windows and macOS over SSH (Parallels-friendly).")
    p.add_argument("--config", type=str, default=str(default_config_path()), help="Path to config.json")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("profile-add", help="Add/update a profile")
    sp.add_argument("--name", required=True)
    sp.add_argument("--host", required=True)
    sp.add_argument("--user", required=True)
    sp.add_argument("--port", type=int, default=22)
    sp.add_argument("--local", default="")
    sp.add_argument("--remote", default="")
    sp.add_argument("--identity", default="")
    sp.add_argument("--no-ensure-remote-dir", action="store_true")

    sd = sub.add_parser("profile-del", help="Delete a profile")
    sd.add_argument("--name", required=True)

    sl = sub.add_parser("profile-list", help="List profiles")

    st = sub.add_parser("test", help="Test SSH connectivity for a profile")
    st.add_argument("--name", required=True)

    sk = sub.add_parser("keygen", help="Generate an ed25519 keypair for passwordless auth")
    sk.add_argument("--path", default=str(Path.home() / ".ssh" / "id_ed25519_parasync"))
    sk.add_argument("--comment", default="parasync")

    si = sub.add_parser("install-key", help="Install a public key onto the remote for passwordless auth")
    si.add_argument("--name", required=True)
    si.add_argument("--pub", default=str(Path.home() / ".ssh" / "id_ed25519_parasync.pub"))

    spush = sub.add_parser("push", help="Copy local -> remote")
    spush.add_argument("--name", required=True)
    spush.add_argument("--local", default=None)
    spush.add_argument("--remote", default=None)

    spull = sub.add_parser("pull", help="Copy remote -> local")
    spull.add_argument("--name", required=True)
    spull.add_argument("--remote", default=None)
    spull.add_argument("--local", default=None)

    return p


def _load(cfg_path: str) -> AppConfig:
    return load_config(Path(cfg_path))


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg_path = Path(args.config)
    cfg = load_config(cfg_path)

    if args.cmd == "profile-add":
        prof = Profile(
            name=args.name,
            host=args.host,
            user=args.user,
            port=args.port,
            local_path=args.local,
            remote_path=args.remote,
            identity_file=args.identity,
            ensure_remote_dir=not args.no_ensure_remote_dir,
        )
        upsert_profile(cfg, prof)
        save_config(cfg, cfg_path)
        print(f"Saved profile '{args.name}' to {cfg_path}")
        return 0

    if args.cmd == "profile-del":
        ok = delete_profile(cfg, args.name)
        save_config(cfg, cfg_path)
        print("Deleted" if ok else "Not found")
        return 0

    if args.cmd == "profile-list":
        if not cfg.profiles:
            print("No profiles.")
            return 0
        for p in cfg.profiles:
            ident = p.identity_file if p.identity_file else "(default)"
            print(f"- {p.name}: {p.user}@{p.host}:{p.port}  local='{p.local_path}'  remote='{p.remote_path}'  key={ident}")
        return 0

    prof = get_profile(cfg, getattr(args, "name", ""))
    if prof is None:
        print(f"Profile not found: {getattr(args, 'name', '')}")
        return 2

    if args.cmd == "test":
        r = test_ssh(prof)
        return _print_result(r.returncode, r.stdout, r.stderr)

    if args.cmd == "keygen":
        r = generate_keypair(Path(args.path), comment=args.comment)
        return _print_result(r.returncode, r.stdout, r.stderr)

    if args.cmd == "install-key":
        r = install_pubkey(prof, Path(args.pub))
        return _print_result(r.returncode, r.stdout, r.stderr)

    if args.cmd == "push":
        local = args.local if args.local is not None else prof.local_path
        remote = args.remote if args.remote is not None else prof.remote_path
        if not local or not remote:
            print("Missing --local/--remote (or set local_path/remote_path in profile).")
            return 2
        r = push(prof, local, remote)
        return _print_result(r.returncode, r.stdout, r.stderr)

    if args.cmd == "pull":
        remote = args.remote if args.remote is not None else prof.remote_path
        local = args.local if args.local is not None else prof.local_path
        if not local or not remote:
            print("Missing --local/--remote (or set local_path/remote_path in profile).")
            return 2
        r = pull(prof, remote, local)
        return _print_result(r.returncode, r.stdout, r.stderr)

    print("Unknown command")
    return 2
