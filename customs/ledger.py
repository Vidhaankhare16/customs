"""The custody ledger: append-only, hash-chained, so an edited or deleted line is detectable.

Every entry carries the hash of the one before it. `verify()` recomputes the chain from the start; changing
any field of any entry, reordering entries or dropping one breaks it at that point.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Verification:
    ok: bool
    entries: int
    broken_at: int | None = None  # seq of the first bad entry
    reason: str = ""


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def entries(self) -> list[dict]:
        with open(self.path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def head(self) -> tuple[int, str]:
        entries = self.entries()
        if not entries:
            return 0, GENESIS
        return entries[-1]["seq"], entries[-1]["hash"]

    def append(self, event: str, ticket: str | None, actor: str, region: str | None = None, **details) -> dict:
        seq, prev = self.head()
        entry = {
            "seq": seq + 1,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            "ticket": ticket,
            "actor": actor,
            "region": region,
            "details": details,
            "prev": prev,
        }
        entry["hash"] = _digest(entry)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
        return entry

    def for_ticket(self, ticket: str) -> list[dict]:
        return [e for e in self.entries() if e.get("ticket") == ticket]

    def verify(self) -> Verification:
        prev = GENESIS
        entries = self.entries()
        for index, entry in enumerate(entries, start=1):
            if entry.get("seq") != index:
                return Verification(False, len(entries), index, "sequence gap or reordering")
            if entry.get("prev") != prev:
                return Verification(False, len(entries), index, "link to previous entry broken")
            if entry.get("hash") != _digest(entry):
                return Verification(False, len(entries), index, "entry contents changed")
            prev = entry["hash"]
        return Verification(True, len(entries))
