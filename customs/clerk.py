"""The clerk process: polls the desk's Switch rooms and carries out the Desk's decisions.

Durability: decisions are persisted before they are announced. Posts go through an outbox that is saved with
the state, so a crash between deciding and posting re-sends the post on restart instead of re-deciding (no
duplicate handoffs, no lost approval requests). Messages already handled are remembered by id.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from customs.config import Config
from customs.desk import Desk, Incoming, Post, RoomView, State
from customs.ledger import Ledger
from customs.redact import Border
from customs.services import GitOrigin, VaultCaseFiles
from customs.switch_client import SwitchClient, SwitchError, flatten

log = logging.getLogger("customs.clerk")
SEEN_LIMIT = 5000
OVERLAP = timedelta(seconds=90)


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


def build_desk(cfg: Config, saved: dict) -> Desk:
    if cfg.vault is None:
        raise SystemExit("config: [vault] path is required (the clerk is the border and reads the vault)")
    cases = VaultCaseFiles(cfg.vault)
    registries = cases.registries()
    repo = GitOrigin(cfg.origin_repo, cfg.vault, cfg.verify_command) if cfg.origin_repo else None
    ledger = Ledger(cfg.data_dir / "ledger.jsonl")
    return Desk(cfg, State.from_json(saved.get("desk")), ledger, cases, repo,
                border_for=lambda pseudonyms: Border(registries, pseudonyms))


class Clerk:
    def __init__(self, cfg: Config, client: SwitchClient, replay: bool = False):
        self.cfg = cfg
        self.client = client
        self.store = StateStore(cfg.data_dir / "state.json")
        saved = self.store.load()
        self.desk = build_desk(cfg, saved)
        self.seen: list[str] = saved.get("seen", [])
        self._seen_set = set(self.seen)
        self.outbox: list[dict] = saved.get("outbox", [])
        start = datetime.now(timezone.utc) - (timedelta(days=7) if replay else timedelta(0))
        self.watermarks: dict[str, str] = saved.get("watermarks", {})
        self._default_mark = start.isoformat()
        # Messages older than the first start are history, not work (unless --replay).
        self.floor_ms: int = saved.get("floor_ms") or int(start.timestamp() * 1000)
        self.room_ids: dict[str, str] = {}

    # ----------------------------------------------------------------------------------------- setup
    def resolve_rooms(self) -> None:
        rooms = {r["name"]: r.get("room_id") or r.get("id") for r in self.client.list_rooms()}
        missing = [name for name in self.cfg.room_keys() if name not in rooms]
        if missing:
            raise SystemExit(f"the clerk is not a member of: {', '.join(missing)}. Add `{self.cfg.clerk_name}` to "
                             f"those rooms (the template does this) and run again.")
        self.room_ids = {name: rooms[name] for name in self.cfg.room_keys()}

    def view(self, room: str) -> RoomView:
        detail = self.client.room_detail(self.room_ids[room])
        holders = {r["name"]: tuple(h["name"] for h in r.get("held_by") or []) for r in detail.get("roles") or []}
        return RoomView(frozenset(detail.get("agent_names") or []), holders)

    # ------------------------------------------------------------------------------------------- loop
    def run(self) -> None:
        self.resolve_rooms()
        log.info("clerk %s watching %s", self.cfg.clerk_name, ", ".join(self.room_ids))
        self.flush()
        while True:
            try:
                self.poll_once()
            except SwitchError as exc:
                log.warning("switch error: %s", exc)
            except OSError as exc:
                log.warning("network error: %s", exc)
            time.sleep(self.cfg.poll_seconds)

    def poll_once(self) -> int:
        handled = 0
        timed = self.desk.tick()  # offices opening/closing, standing orders expiring
        if timed:
            self.outbox.extend({"room": p.room, "text": p.text} for p in timed)
            self.save()
            self.flush()
        for room, room_id in self.room_ids.items():
            mark = datetime.fromisoformat(self.watermarks.get(room, self._default_mark))
            entries = flatten(self.client.read_context(room_id, since=mark - OVERLAP, limit=100))
            fresh = [e for e in entries if e["id"] not in self._seen_set and e.get("timestamp", 0) >= self.floor_ms]
            if not fresh:
                continue
            view = self.view(room)
            for entry in fresh:
                self._remember(entry["id"])
                ts = datetime.fromtimestamp(entry.get("timestamp", 0) / 1000, timezone.utc)
                if ts > mark:
                    mark = ts
                    self.watermarks[room] = ts.isoformat()
                if entry.get("sender_name") == self.cfg.clerk_name:
                    continue
                kind = entry.get("sender_kind") or ("agent" if entry.get("sender_name") in view.agent_names else "user")
                msg = Incoming(room, entry["id"], entry.get("sender_name", ""), kind, entry.get("body", ""), entry.get("timestamp", 0))
                posts = self.desk.handle(msg, view)
                self.outbox.extend({"room": p.room, "text": p.text} for p in posts)
                handled += 1
                self.save()  # decision persisted before it is announced
                self.flush()
        self.save()
        return handled

    def flush(self) -> None:
        while self.outbox:
            post = self.outbox[0]
            self.client.post(self.room_ids[post["room"]], post["text"])
            self.outbox.pop(0)
            self.save()

    # ---------------------------------------------------------------------------------------- helpers
    def _remember(self, message_id: str) -> None:
        self.seen.append(message_id)
        self._seen_set.add(message_id)
        if len(self.seen) > SEEN_LIMIT:
            dropped = self.seen[: len(self.seen) - SEEN_LIMIT]
            self.seen = self.seen[-SEEN_LIMIT:]
            self._seen_set.difference_update(dropped)

    def save(self) -> None:
        self.store.save({"desk": self.desk.state.to_json(), "seen": self.seen, "outbox": self.outbox,
                         "watermarks": self.watermarks, "floor_ms": self.floor_ms})


def post_once(posts: list[Post]) -> None:  # pragma: no cover - convenience for scripts
    for p in posts:
        print(f"[{p.room}] {p.text}")
