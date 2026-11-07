"""Command line: `python -m customs <command>`.

  register   register the clerk with a Switch server and save its credentials
  check      show what the clerk can see: rooms, members, roles
  run        run the clerk
  ledger     show or verify the custody ledger (offline)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from customs import config as config_mod
from customs.ledger import Ledger
from customs.switch_client import Credentials, SwitchClient, SwitchError, health, register

DEFAULT_CONFIG = Path("config/customs.toml")


def _creds_path(cfg) -> Path:
    return cfg.data_dir / "credentials.json"


def _load_creds(cfg) -> Credentials:
    env = {k: os.environ.get(k) for k in ("SWITCH_BASE_URL", "CUSTOMS_AGENT_ID", "CUSTOMS_API_KEY")}
    if all(env.values()):
        return Credentials(env["SWITCH_BASE_URL"].rstrip("/"), env["CUSTOMS_AGENT_ID"], env["CUSTOMS_API_KEY"])
    path = _creds_path(cfg)
    if not path.exists():
        raise SystemExit(f"no credentials: run `python -m customs register` first (or set SWITCH_BASE_URL, "
                         f"CUSTOMS_AGENT_ID, CUSTOMS_API_KEY)")
    return Credentials(**json.loads(path.read_text(encoding="utf-8")))


def cmd_register(args, cfg) -> int:
    if not health(args.base_url):
        print(f"{args.base_url}/health did not answer. Is Switch running, and is this the agent bridge URL?")
        return 1
    key = args.registration_key or os.environ.get("SWITCH_REGISTRATION_KEY")
    if not key:
        print("pass --registration-key or set SWITCH_REGISTRATION_KEY (create one on the Gateway's API Keys page)")
        return 1
    creds = register(args.base_url, key, cfg.clerk_name,
                     "Customs clerk: the deterministic border between regional rooms. Not an AI.", args.overwrite)
    path = _creds_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(vars(creds), indent=2), encoding="utf-8")
    print(f"registered {cfg.clerk_name} as {creds.agent_id}; credentials saved to {path} (keep it private)")
    return 0


def cmd_check(args, cfg) -> int:
    client = SwitchClient(_load_creds(cfg))
    try:
        rooms = {r["name"]: r.get("room_id") or r.get("id") for r in client.list_rooms()}
    except SwitchError as exc:
        print(f"cannot list rooms: {exc}")
        return 1
    ok = True
    for name in cfg.room_keys():
        if name not in rooms:
            ok = False
            print(f"MISSING  {name}: the clerk is not a member")
            continue
        detail = client.room_detail(rooms[name])
        roles = ", ".join(f"{r['name']}{'*' if r.get('exclusive') else ''}="
                          f"{'/'.join(h['name'] for h in r.get('held_by') or []) or 'free'}"
                          for r in detail.get("roles") or []) or "none"
        print(f"ok       {name}: agents={detail.get('agent_names')} people={detail.get('connected_user_names')} roles={roles}")
    return 0 if ok else 1


def cmd_run(args, cfg) -> int:
    from customs.clerk import Clerk

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Clerk(cfg, SwitchClient(_load_creds(cfg)), replay=args.replay).run()
    return 0


def cmd_ledger(args, cfg) -> int:
    ledger = Ledger(cfg.data_dir / "ledger.jsonl")
    if args.action == "verify":
        result = ledger.verify()
        print(f"{'intact' if result.ok else 'BROKEN'}: {result.entries} entries"
              + ("" if result.ok else f", first bad entry {result.broken_at} ({result.reason})"))
        return 0 if result.ok else 1
    for entry in ledger.for_ticket(args.ticket) if args.ticket else ledger.entries():
        print(f"{entry['seq']:>4} {entry['ts']} {entry['event']:<24} {entry['actor']:<20} {entry.get('ticket') or '-':<9} {entry['hash'][:12]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; chat text carries emoji
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m customs", description="Customs clerk")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="register the clerk with Switch")
    reg.add_argument("--base-url", default=os.environ.get("SWITCH_BASE_URL", "http://localhost:8000"))
    reg.add_argument("--registration-key")
    reg.add_argument("--overwrite", action="store_true", help="re-issue the key if the name exists")
    sub.add_parser("check", help="show rooms, members and roles the clerk sees")
    run = sub.add_parser("run", help="run the clerk")
    run.add_argument("--replay", action="store_true", help="also process the last 7 days of room history")
    led = sub.add_parser("ledger", help="show or verify the ledger")
    led.add_argument("action", choices=["show", "verify"])
    led.add_argument("ticket", nargs="?")
    args = parser.parse_args(argv)
    cfg = config_mod.load(args.config)
    return {"register": cmd_register, "check": cmd_check, "run": cmd_run, "ledger": cmd_ledger}[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
