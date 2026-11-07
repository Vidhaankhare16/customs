"""Desk configuration: regions, rooms, roles, approvers and the routes work may take."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Region:
    key: str
    label: str  # "Bengaluru"
    room: str  # Switch room name
    role: str  # exclusive role whose holder may hand work out of this room
    approvers: tuple[str, ...]  # people (chat names) who sign what leaves this region
    residency: tuple[str, ...]  # data residencies this region may hold, e.g. ("EU",)
    utc_offset: str = "+00:00"
    office_hours: tuple[int, int] = (9, 18)

    def tz(self) -> timezone:
        sign, hours, minutes = _OFFSET.match(self.utc_offset).groups()  # validated on load
        delta = timedelta(hours=int(hours), minutes=int(minutes))
        return timezone(-delta if sign == "-" else delta)

    def local_time(self, now: datetime) -> datetime:
        return now.astimezone(self.tz())

    def office_open(self, now: datetime) -> bool:
        start, end = self.office_hours
        return start <= self.local_time(now).hour < end


@dataclass(frozen=True)
class Config:
    desk_name: str
    clerk_name: str
    intake_room: str
    start_region: str
    release_region: str
    regions: dict[str, Region]
    routes: frozenset[tuple[str, str]]
    vault: Path | None
    origin_repo: Path | None
    data_dir: Path
    poll_seconds: float = 2.0
    independent_verification: bool = True
    verify_command: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)

    def region_for_room(self, room: str) -> Region | None:
        return next((r for r in self.regions.values() if r.room == room), None)

    def room_keys(self) -> list[str]:
        return [self.intake_room, *(r.room for r in self.regions.values())]


def load(path: str | Path) -> Config:
    path = Path(path)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent

    def rel(value: str | None) -> Path | None:
        if not value:
            return None
        p = Path(value).expanduser()
        return p if p.is_absolute() else (base / p).resolve()

    try:
        regions = {}
        for key, r in raw["regions"].items():
            if not _OFFSET.match(r.get("utc_offset", "+00:00")):
                raise ConfigError(f"regions.{key}.utc_offset must look like +05:30")
            approvers = tuple(r["approvers"])
            if not approvers:
                raise ConfigError(f"regions.{key}.approvers must name at least one person")
            regions[key] = Region(
                key=key,
                label=r["label"],
                room=r["room"],
                role=r["role"],
                approvers=approvers,
                residency=tuple(r.get("residency", [])),
                utc_offset=r.get("utc_offset", "+00:00"),
                office_hours=tuple(r.get("office_hours", [9, 18])),
            )
        routes = frozenset(tuple(pair) for pair in raw["routes"]["allowed"])
        for a, b in routes:
            if a not in regions or b not in regions:
                raise ConfigError(f"route {a}->{b} names an unknown region")
        cfg = Config(
            desk_name=raw["desk"]["name"],
            clerk_name=raw["clerk"]["agent_name"],
            intake_room=raw["desk"]["intake_room"],
            start_region=raw["desk"]["start_region"],
            release_region=raw["desk"]["release_region"],
            regions=regions,
            routes=routes,
            vault=rel(raw.get("vault", {}).get("path")),
            origin_repo=rel(raw.get("release", {}).get("origin_repo")),
            data_dir=rel(raw["clerk"].get("data_dir", ".customs")),
            poll_seconds=float(raw["clerk"].get("poll_seconds", 2)),
            independent_verification=bool(raw.get("release", {}).get("independent_verification", True)),
            verify_command=tuple(raw.get("release", {}).get("verify_command", [])),
            extra=raw,
        )
    except KeyError as exc:
        raise ConfigError(f"missing config key: {exc}") from exc
    for key in (cfg.start_region, cfg.release_region):
        if key not in regions:
            raise ConfigError(f"unknown region {key!r}")
    return cfg
