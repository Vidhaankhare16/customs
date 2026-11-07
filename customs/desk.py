"""The clerk's decisions, as a pure state machine.

`Desk.handle(message, view)` takes one room message plus a snapshot of who is in the room and who holds which
role, and returns the posts the clerk should make. `Desk.tick()` is called on every poll and handles time:
offices opening and closing, standing orders expiring. Neither does I/O of its own: the Switch client, the
clock, the vault and git are injected, so every rule here is unit-tested without a server.

The rules, in one place.

Access (data stays where it belongs):
* A ticket is always in the custody of exactly one region. Only the agent holding that region's role may hand
  it on, and only along a configured route.
* Text leaving a data-resident region for one that isn't must contain no personal data. If it does, the
  handoff is blocked (not repaired) and the author told where. Identifiers are pseudonymised on the way out
  and re-identified only on the way back in.

Authority (the right person signs, even while asleep):
* Every crossing needs a person's signature from the region the work is leaving (for a release: the resident
  region), pinned to the digest of the exact text. Agents cannot sign. Signatures are single-use.
* People sleep; agents don't. Before going off duty an approver may leave a **standing order**: a bounded,
  expiring, single-use delegation ("release TKT-0001 if your independent check passes, until 09:00"). The clerk
  applies it only when every condition holds, and records it as that person's signature under that order.
* Requests that reach a region while its office is closed say when its people are back. When an office opens,
  its people get a briefing of what happened overnight and what waits for them.

Release:
* A release is re-verified independently by the clerk at the exact commit before anyone (or any standing
  order) may sign it, and only that commit is merged.

Every decision, including every refusal and every use of delegated authority, is written to the
hash-chained ledger.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from customs import handoff as handoff_mod
from customs.config import Config, Region
from customs.ledger import Ledger
from customs.redact import Border, Pseudonyms

APPROVAL = re.compile(r"^\s*(approve|reject)\s+(H-\d+)\b(.*)$", re.IGNORECASE | re.DOTALL)
STANDING_ORDER = re.compile(
    r"^(release|handoff)\s+(TKT-\d{4}|any)\s+until\s+(\d{1,2}):(\d{2})\s*$", re.IGNORECASE)
CLOCK_TO = re.compile(r"^([a-z]+)\s+(\d{1,2}):(\d{2})$", re.IGNORECASE)
CLOCK_BY = re.compile(r"^\+(\d{1,2})h(?:(\d{1,2})m)?$", re.IGNORECASE)


# --------------------------------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class Incoming:
    room: str  # room name
    message_id: str
    sender_name: str
    sender_kind: str  # "user" | "agent" | "platform"
    body: str
    timestamp: int = 0


@dataclass(frozen=True)
class RoomView:
    agent_names: frozenset[str] = frozenset()
    role_holders: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Post:
    room: str
    text: str


# ----------------------------------------------------------------------------------------- services
class CaseFiles(Protocol):
    def customer(self, customer_id: str) -> dict | None: ...

    def case_file(self, customer_id: str, border: Border) -> str: ...


class Repo(Protocol):
    def commit_exists(self, commit: str) -> bool: ...

    def verify(self, commit: str) -> tuple[bool, str]: ...

    def merge(self, commit: str, branch: str) -> tuple[bool, str]: ...


# ---------------------------------------------------------------------------------------------- state
@dataclass
class Ticket:
    id: str
    customer_id: str
    customer_token: str
    residency: str
    custody: str  # region key
    status: str = "open"  # open | released
    title: str = ""
    history: list[dict] = field(default_factory=list)  # {"from","to","signed_by","digest","at"}


@dataclass
class Pending:
    id: str
    ticket: str
    source: str  # region key
    to: str  # region key or "release"
    author: str
    outbound: str  # the exact text that will be delivered
    digest: str
    handoff: dict
    status: str = "awaiting"  # awaiting | approved | rejected
    verification: str = ""
    verified: bool = False


@dataclass
class StandingOrder:
    id: str
    region: str  # whose signature it stands in for
    created_by: str
    action: str  # "release" | "handoff"
    ticket: str  # "TKT-0001" or "any"
    expires_at: str  # ISO, UTC
    uses_left: int = 1
    status: str = "active"  # active | used | revoked | expired
    created_at: str = ""

    def condition(self) -> str:
        if self.action == "release":
            return "my own independent reconciliation of that exact commit passes"
        return "it passes the border check"

    def scope(self) -> str:
        what = "the release of" if self.action == "release" else "a handoff out of your region for"
        return f"{what} {'any ticket' if self.ticket == 'any' else self.ticket}"


@dataclass
class State:
    tickets: dict[str, Ticket] = field(default_factory=dict)
    pending: dict[str, Pending] = field(default_factory=dict)
    orders: dict[str, StandingOrder] = field(default_factory=dict)
    pseudonyms: Pseudonyms = field(default_factory=Pseudonyms)
    next_ticket: int = 1
    next_handoff: int = 1
    next_order: int = 1
    clock_offset: float = 0.0  # seconds; non-zero only in demo time travel
    office: dict[str, bool] = field(default_factory=dict)  # last known open/closed per region
    closed_at: dict[str, str] = field(default_factory=dict)  # when each region last closed (ISO)

    def to_json(self) -> dict:
        return {
            "tickets": {k: vars(v) for k, v in self.tickets.items()},
            "pending": {k: vars(v) for k, v in self.pending.items()},
            "orders": {k: vars(v) for k, v in self.orders.items()},
            "pseudonyms": self.pseudonyms.to_json(),
            "next_ticket": self.next_ticket,
            "next_handoff": self.next_handoff,
            "next_order": self.next_order,
            "clock_offset": self.clock_offset,
            "office": self.office,
            "closed_at": self.closed_at,
        }

    @classmethod
    def from_json(cls, data: dict | None) -> "State":
        data = data or {}
        return cls(
            tickets={k: Ticket(**v) for k, v in data.get("tickets", {}).items()},
            pending={k: Pending(**v) for k, v in data.get("pending", {}).items()},
            orders={k: StandingOrder(**v) for k, v in data.get("orders", {}).items()},
            pseudonyms=Pseudonyms.from_json(data.get("pseudonyms")),
            next_ticket=data.get("next_ticket", 1),
            next_handoff=data.get("next_handoff", 1),
            next_order=data.get("next_order", 1),
            clock_offset=data.get("clock_offset", 0.0),
            office=dict(data.get("office", {})),
            closed_at=dict(data.get("closed_at", {})),
        )


def _person(name: str) -> str:
    """Chat platforms spell the same person '@Berlin-Lead' or 'berlin-lead'; compare them as one."""
    return name.strip().lstrip("@").casefold()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _span(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    return f"{minutes // 60}h {minutes % 60:02d}m"


# ----------------------------------------------------------------------------------------------- desk
class Desk:
    def __init__(
        self,
        config: Config,
        state: State,
        ledger: Ledger,
        cases: CaseFiles,
        repo: Repo | None,
        border_for: Callable[[Pseudonyms], Border],
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.cfg = config
        self.state = state
        self.ledger = ledger
        self.cases = cases
        self.repo = repo
        self.border = border_for(state.pseudonyms)
        self._wall = now

    def now(self) -> datetime:
        return self._wall() + timedelta(seconds=self.state.clock_offset)

    def log(self, event: str, ticket: str | None, actor: str, region: str | None = None, **details) -> dict:
        return self.ledger.append(event, ticket, actor, region, at=self.now(), **details)

    # -------------------------------------------------------------------------------------- dispatch
    def handle(self, msg: Incoming, view: RoomView) -> list[Post]:
        if msg.sender_name == self.cfg.clerk_name:
            return []
        body = msg.body.strip()
        if handoff_mod.extract(body) is not None:
            return self._handoff(msg, view)
        approval = APPROVAL.match(self._strip_mention(body))
        if approval:
            verb, pid, rest = approval.groups()
            return self._decide(msg, view, pid.upper(), verb.lower() == "approve", rest.strip())
        if not self._mentions_clerk(body):
            return []
        command, _, args = self._strip_mention(body).partition(" ")
        command, args = command.lower().strip(), args.strip()
        if command == "open":
            return self._open(msg, args)
        if command == "standing-order":
            return self._standing_order(msg, view, args)
        if command == "revoke":
            return self._revoke(msg, view, args.upper())
        if command == "orders":
            return [Post(msg.room, self._orders_view())]
        if command == "time":
            return self._time_travel(msg, view, args)
        if command == "status":
            return [Post(msg.room, self._status())]
        if command == "ledger":
            return [Post(msg.room, self._ledger_view(args.upper()))]
        if command in ("verify-ledger", "verify"):
            return [Post(msg.room, self._verify_ledger())]
        return [Post(msg.room, self._help())]

    # ------------------------------------------------------------------------------------------ time
    def tick(self) -> list[Post]:
        """Called on every poll: expire standing orders; brief people as their office opens or closes."""
        now = self.now()
        posts: list[Post] = []
        for order in self.state.orders.values():
            if order.status == "active" and now >= datetime.fromisoformat(order.expires_at):
                order.status = "expired"
                self.log("standing_order_expired", None if order.ticket == "any" else order.ticket,
                         self.cfg.clerk_name, order.region, order=order.id)
        for region in self.cfg.regions.values():
            is_open = region.office_open(now)
            was_open = self.state.office.get(region.key)
            self.state.office[region.key] = is_open
            if was_open is None:
                if not is_open:
                    self.state.closed_at[region.key] = now.isoformat()
                continue
            if was_open and not is_open:
                self.state.closed_at[region.key] = now.isoformat()
                posts += self._closing_note(region)
            elif not was_open and is_open:
                posts += self._morning_briefing(region)
        return posts

    def _closing_note(self, region: Region) -> list[Post]:
        mention = " ".join(f"@{a}" for a in region.approvers)
        lines = [f"{mention} **{region.label} is closing** ({self._clock_line(region)})."]
        waiting = [p for p in self.state.pending.values() if p.status == "awaiting" and self._signer(p).key == region.key]
        if waiting:
            lines.append("Still waiting for your signature: " + ", ".join(f"{p.id} ({p.ticket})" for p in waiting) + ".")
        active = [o for o in self.state.orders.values() if o.status == "active" and o.region == region.key]
        if active:
            lines.append("Standing orders in force tonight: " + ", ".join(f"{o.id} ({o.scope()})" for o in active) + ".")
        open_tickets = [t for t in self.state.tickets.values() if t.status == "open"]
        if open_tickets and not active:
            example = f"standing-order {'release' if region.key == self.cfg.release_region else 'handoff'} {open_tickets[0].id} until {region.office_hours[0]:02d}:00"
            lines.append(f"Agents keep working overnight. If something will need your signature before you're back, "
                         f"you can leave a bounded standing order, e.g. `clerk {example}`.")
        return [Post(region.room, "\n".join(lines))]

    def _morning_briefing(self, region: Region) -> list[Post]:
        since = datetime.fromisoformat(self.state.closed_at.get(region.key, self.now().isoformat()))
        mention = " ".join(f"@{a}" for a in region.approvers)
        events = []
        for e in self.ledger.entries():
            if datetime.fromisoformat(e["ts"]) < since:
                continue
            d = e.get("details") or {}
            local = datetime.fromisoformat(e["ts"]).astimezone(region.tz()).strftime("%H:%M")
            if e["event"] == "standing_order_used" and e["region"] == region.key:
                events.append(f"- {local} {d.get('handoff')} for {e['ticket']} was signed under your standing order {d.get('order')}")
            elif e["event"] == "released" and e["region"] == region.key:
                events.append(f"- {local} **{e['ticket']} was released**: `main` is at `{str(d.get('commit'))[:10]}`")
            elif e["event"] == "custody_transferred" and d.get("to") == region.key:
                events.append(f"- {local} {e['ticket']} arrived in {region.label}'s custody")
            elif e["event"] == "handoff_blocked" and e["region"] == region.key:
                events.append(f"- {local} a handoff for {e['ticket']} was blocked at the border")
        waiting = [p for p in self.state.pending.values() if p.status == "awaiting" and self._signer(p).key == region.key]
        lines = [f"{mention} **Good morning, {region.label}** ({self._clock_line(region)})."]
        lines.append("While you were away:\n" + "\n".join(events) if events else "Nothing needed you overnight.")
        if waiting:
            lines.append("Waiting for your signature: " + ", ".join(f"`approve {p.id}` ({p.ticket})" for p in waiting))
        return [Post(region.room, "\n\n".join(lines))]

    def _time_travel(self, msg: Incoming, view: RoomView, args: str) -> list[Post]:
        if not self.cfg.time_travel:
            return [Post(msg.room, "Time travel is off (it's a demo setting: `[demo] time_travel = true`).")]
        if msg.sender_kind != "user" or msg.sender_name in view.agent_names:
            return [Post(msg.room, "Only a person can move the desk clock.")]
        now = self.now()
        if args.lower() == "reset":
            self.state.clock_offset = 0.0
        elif m := CLOCK_BY.match(args):
            self.state.clock_offset += int(m.group(1)) * 3600 + int(m.group(2) or 0) * 60
        elif m := CLOCK_TO.match(args):
            region = self.cfg.regions.get(m.group(1).lower()) or next(
                (r for r in self.cfg.regions.values() if r.label.lower() == m.group(1).lower()), None)
            if region is None:
                return [Post(msg.room, f"No region `{m.group(1)}`.")]
            local = region.local_time(now)
            target = local.replace(hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0)
            if target <= local:
                target += timedelta(days=1)
            self.state.clock_offset += (target - local).total_seconds()
        else:
            return [Post(msg.room, "Usage: `time eu 18:05`, `time +8h`, `time reset` (demo only).")]
        self.log("clock_moved", None, msg.sender_name, offset_seconds=self.state.clock_offset)
        clocks = " | ".join(self._clock_line(r) for r in self.cfg.regions.values())
        return [Post(msg.room, f"Desk clock moved by {msg.sender_name} (demo). {clocks}")] + self.tick()

    # ------------------------------------------------------------------------------------------ open
    def _open(self, msg: Incoming, args: str) -> list[Post]:
        if msg.room != self.cfg.intake_room:
            return [Post(msg.room, f"Tickets are opened in `{self.cfg.intake_room}`.")]
        if msg.sender_kind != "user":
            self.log("open_refused", None, msg.sender_name, reason="sender is not a person")
            return [Post(msg.room, "Refused: only a person can open a ticket.")]
        customer_id, _, title = args.partition(" ")
        customer = self.cases.customer(customer_id)
        if customer is None:
            return [Post(msg.room, f"No customer `{customer_id or '?'}` in the registry. Usage: `open <customer_id> <what is wrong>`")]
        tid = f"TKT-{self.state.next_ticket:04d}"
        self.state.next_ticket += 1
        start = self.cfg.regions[self.cfg.start_region]
        token = self.border.pseudonymise(customer["legal_name"])
        ticket = Ticket(tid, customer_id, token, customer["residency"], start.key, title=self.border.scrub(title))
        self.state.tickets[tid] = ticket
        resident = self._resident_region(ticket)
        self.log("ticket_opened", tid, msg.sender_name, customer=token, residency=ticket.residency)
        self.log("custody_transferred", tid, self.cfg.clerk_name, start.key, to=start.key)
        case = self.cases.case_file(customer_id, self.border)
        resident_note = (
            f"The customer's records are {ticket.residency}-resident and stay in **{resident.label}**. "
            f"You get a pseudonymised case file; anything that needs the real records goes to {resident.label} "
            f"through a handoff."
            if resident and resident.key != start.key
            else ""
        )
        return [
            Post(
                start.room,
                f"@{start.role} **{tid}** is in your custody. Customer {token}: {ticket.title}\n\n"
                f"{resident_note}\n\n{case}",
            ),
            Post(self.cfg.intake_room, f"**{tid}** opened for {token} ({ticket.residency} data). "
                                       + " | ".join(self._clock_line(r) for r in self.cfg.regions.values())),
        ]

    # --------------------------------------------------------------------------------------- handoff
    def _handoff(self, msg: Incoming, view: RoomView) -> list[Post]:
        source = self.cfg.region_for_room(msg.room)
        if source is None:
            return [Post(msg.room, "Handoffs are filed in a regional room, not here.")]
        holders = view.role_holders.get(source.role, ())
        if msg.sender_name not in holders:
            who = ", ".join(holders) if holders else "nobody"
            return self._refuse(
                msg, source, None, "handoff_refused",
                f"only the holder of the `{source.role}` role in `{source.room}` can hand work out of it "
                f"(current holder: {who}). Assume the role first.",
            )
        parsed, errors = handoff_mod.parse(msg.body)
        if errors:
            seen = re.search(r"TKT-\d{4}", handoff_mod.extract(msg.body) or "")  # count it on the ticket's card
            return self._refuse(msg, source, seen.group(0) if seen else None, "handoff_refused",
                                "the handoff is not valid:\n- " + "\n- ".join(errors))
        ticket = self.state.tickets.get(parsed.ticket)
        if ticket is None or ticket.status != "open":
            return self._refuse(msg, source, parsed.ticket, "handoff_refused", f"{parsed.ticket} is not an open ticket.")
        if ticket.custody != source.key:
            holder = self.cfg.regions[ticket.custody].label
            return self._refuse(msg, source, ticket.id, "handoff_refused", f"{ticket.id} is in {holder}'s custody, not {source.label}'s.")

        release = parsed.to == "release"
        if release:
            if source.key != self.cfg.release_region:
                return self._refuse(msg, source, ticket.id, "handoff_refused", f"releases are requested from {self.cfg.regions[self.cfg.release_region].label}.")
            if not parsed.commit:
                return self._refuse(msg, source, ticket.id, "handoff_refused", "a release names the exact `branch` and `commit` to ship.")
            dest = None
        else:
            dest = self.cfg.regions.get(parsed.to)
            if dest is None:
                return self._refuse(msg, source, ticket.id, "handoff_refused", f"`{parsed.to}` is not a region ({', '.join(self.cfg.regions)}) or `release`.")
            if (source.key, dest.key) not in self.cfg.routes:
                return self._refuse(msg, source, ticket.id, "handoff_refused", f"there is no route {source.label} -> {dest.label}.")

        if parsed.commit and self.repo is not None and not self.repo.commit_exists(parsed.commit):
            return self._refuse(msg, source, ticket.id, "handoff_refused", f"commit `{parsed.commit}` is not on the shared origin. Push it first.")

        # -- the border ------------------------------------------------------------------------------
        outgoing = parsed
        if not release:
            leaving_residency = self._holds(source, ticket) and not self._holds(dest, ticket)
            entering_residency = self._holds(dest, ticket) and not self._holds(source, ticket)
            findings = [f for loc, text in parsed.texts() for f in self.border.find_personal(text, loc)]
            if findings and (leaving_residency or entering_residency):
                where = "\n".join(f"- {f.category.replace('_', ' ')} in `{f.location}`" for f in findings)
                self.log("handoff_blocked", ticket.id, msg.sender_name, source.key, to=dest.key,
                         findings=[f"{f.category}@{f.location}" for f in findings])
                return [Post(msg.room,
                    f"@{msg.sender_name} **Blocked at the border.** This handoff would take personal data out of "
                    f"{source.label}:\n{where}\n\nNothing was sent. Rewrite those items without it (describe the "
                    f"pattern, not the person or the value) and file the handoff again.")]
            if leaving_residency:
                outgoing = parsed.map_texts(self.border.pseudonymise)
            elif entering_residency:
                outgoing = parsed.map_texts(self.border.reidentify)

        pid = f"H-{self.state.next_handoff}"
        self.state.next_handoff += 1
        header = (
            f"**{ticket.id} handoff {source.label} -> {dest.label}**" if dest
            else f"**{ticket.id} release request from {source.label}**"
        )
        outbound = f"{header} (from `{msg.sender_name}`)\n\n{outgoing.render()}"
        pending = Pending(pid, ticket.id, source.key, dest.key if dest else "release", msg.sender_name,
                          outbound, digest(outbound), outgoing.to_json())

        if release and self.cfg.independent_verification and self.repo is not None:
            ok, summary = self.repo.verify(parsed.commit)
            self.log("independent_verification", ticket.id, self.cfg.clerk_name, source.key,
                     commit=parsed.commit, passed=ok)
            if not ok:
                return [Post(msg.room,
                    f"@{msg.sender_name} **Release refused.** I reconciled commit `{parsed.commit}` myself and it "
                    f"does not pass:\n```\n{summary}\n```\nNothing ships until it does.")]
            pending.verification, pending.verified = summary, True

        self.state.pending[pid] = pending
        self.log("handoff_filed", ticket.id, msg.sender_name, source.key, handoff=pid,
                 to=pending.to, digest=pending.digest, commit=parsed.commit)
        verified = f"\n\nIndependent check by the clerk at `{parsed.commit}`:\n```\n{pending.verification}\n```" if pending.verification else ""

        # -- authority: a person, or a person's standing order -----------------------------------------
        signer_region = self._signer(pending)
        order = self._matching_order(pending, signer_region)
        if order is not None:
            order.uses_left -= 1
            if order.uses_left <= 0:
                order.status = "used"
            self.log("standing_order_used", ticket.id, self.cfg.clerk_name, signer_region.key,
                     order=order.id, handoff=pid, digest=pending.digest, on_behalf_of=order.created_by)
            note = Post(msg.room,
                f"**{pid}** passed the border check.{verified}\n\n{signer_region.label} is off duty "
                f"({self._clock_line(signer_region)}), but **{order.created_by}** left standing order **{order.id}** "
                f"for {order.scope()} if {order.condition()}. It does, so I'm signing on their behalf (digest "
                f"`{pending.digest}`). They'll see it in their morning briefing.")
            return [note] + self._approve(pending, f"{order.created_by} (standing order {order.id})")

        mention = " ".join(f"@{a}" for a in signer_region.approvers)
        crossing = f"This exact text goes to `{dest.room}`:" if dest else "This is what you are approving:"
        off_duty = ""
        if not signer_region.office_open(self.now()):
            opens = signer_region.next_open(self.now())
            off_duty = (f"\n\n**{signer_region.label} is off duty** ({self._clock_line(signer_region)}). This waits for "
                        f"{', '.join(signer_region.approvers)}; their office opens at {opens:%H:%M} local, in "
                        f"{_span(opens - self.now())}. @{msg.sender_name}: don't wait idle, carry on with other work.")
        return [Post(msg.room,
            f"{mention} **{pid}** passed the border check and needs your signature.{verified}\n\n"
            f"{crossing} (digest `{pending.digest}`)\n\n> " + outbound.replace("\n", "\n> ") +
            f"\n\nReply `approve {pid}` or `reject {pid} <reason>`.{off_duty}")]

    # -------------------------------------------------------------------------------------- approval
    def _decide(self, msg: Incoming, view: RoomView, pid: str, approve: bool, reason: str) -> list[Post]:
        pending = self.state.pending.get(pid)
        if pending is None:
            return [Post(msg.room, f"There is no handoff {pid}.")]
        if pending.status != "awaiting":
            return [Post(msg.room, f"{pid} was already {pending.status}. Approvals are single-use.")]
        ticket = self.state.tickets[pending.ticket]
        source = self.cfg.regions[pending.source]
        signing_region = self._signer(pending)
        if msg.room != signing_region.room:
            return [Post(msg.room, f"{pid} is signed in `{signing_region.room}`.")]
        if not self._is_person(msg, view):
            self.log("approval_refused", ticket.id, msg.sender_name, source.key, handoff=pid, reason="sender is not a person")
            return [Post(msg.room, f"**Refused:** {pid} must be signed by a person, and `{msg.sender_name}` is not one. Logged.")]
        if not self._is_approver(msg.sender_name, signing_region):
            self.log("approval_refused", ticket.id, msg.sender_name, source.key, handoff=pid, reason="not an approver")
            return [Post(msg.room, f"**Refused:** `{msg.sender_name}` is not an approver for {signing_region.label} "
                                   f"(approvers: {', '.join(signing_region.approvers)}). Logged.")]

        if not approve:
            pending.status = "rejected"
            self.log("handoff_rejected", ticket.id, msg.sender_name, source.key, handoff=pid, reason=reason or "-")
            return [Post(msg.room, f"@{pending.author} {pid} rejected by {msg.sender_name}: {reason or 'no reason given'}. "
                                   f"{ticket.id} stays with {source.label}.")]
        return self._approve(pending, msg.sender_name)

    def _approve(self, pending: Pending, signer: str) -> list[Post]:
        """Carry out an approved crossing. `signer` is a person, or a person under a standing order."""
        pending.status = "approved"
        ticket = self.state.tickets[pending.ticket]
        source = self.cfg.regions[pending.source]
        signing_room = self._signer(pending).room
        self.log("handoff_approved", ticket.id, signer, source.key, handoff=pending.id, digest=pending.digest)
        if pending.to == "release":
            return self._release(signing_room, ticket, pending, signer)

        dest = self.cfg.regions[pending.to]
        ticket.custody = dest.key
        ticket.history.append({"from": source.key, "to": dest.key, "signed_by": signer,
                               "digest": pending.digest, "at": self.now().isoformat(timespec="seconds")})
        self.log("custody_transferred", ticket.id, self.cfg.clerk_name, dest.key, to=dest.key, handoff=pending.id)
        return [
            Post(dest.room, f"@{dest.role} **{ticket.id}** is now in your custody, signed out of {source.label} "
                            f"by {signer}.\n\n{pending.outbound}"),
            Post(signing_room, f"{pending.id} approved. {ticket.id} is now with {dest.label}. {self._clock_line(dest)}"),
            Post(self.cfg.intake_room, f"**{ticket.id}**: {source.label} -> {dest.label}, signed by {signer}. "
                                       f"{self._clock_line(dest)}"),
        ]

    def _release(self, room: str, ticket: Ticket, pending: Pending, signer: str) -> list[Post]:
        handoff = pending.handoff
        if self.repo is None:
            ok, detail = False, "no origin repository is configured"
        else:
            ok, detail = self.repo.merge(handoff["commit"], handoff["branch"])
        if not ok:
            self.log("release_failed", ticket.id, self.cfg.clerk_name, pending.source, detail=detail)
            return [Post(room, f"Release of {ticket.id} failed: {detail}")]
        ticket.status = "released"
        ticket.history.append({"from": pending.source, "to": "release", "signed_by": signer,
                               "digest": pending.digest, "at": self.now().isoformat(timespec="seconds")})
        self.log("released", ticket.id, self.cfg.clerk_name, pending.source, commit=handoff["commit"], detail=detail)
        return [Post(room, f"**{ticket.id} released.** {detail}"), Post(self.cfg.intake_room, self._custody_card(ticket))]

    # ------------------------------------------------------------------------------- standing orders
    def _standing_order(self, msg: Incoming, view: RoomView, args: str) -> list[Post]:
        region = self.cfg.region_for_room(msg.room)
        usage = f"Usage, in your region's room: `clerk standing-order <release|handoff> <TKT-0001|any> until <HH:MM>`"
        if region is None:
            return [Post(msg.room, usage)]
        if not self._is_person(msg, view) or not self._is_approver(msg.sender_name, region):
            self.log("standing_order_refused", None, msg.sender_name, region.key, reason="not an approver of this region")
            return [Post(msg.room, f"**Refused:** only {region.label}'s approvers ({', '.join(region.approvers)}) can "
                                   f"delegate {region.label}'s signature. Logged.")]
        m = STANDING_ORDER.match(args)
        if not m:
            return [Post(msg.room, usage)]
        action, ticket_id, hh, mm = m.group(1).lower(), m.group(2).upper(), int(m.group(3)), int(m.group(4))
        if action == "release" and region.key != self.cfg.release_region:
            return [Post(msg.room, f"Releases are signed by {self.cfg.regions[self.cfg.release_region].label}, not {region.label}.")]
        if action == "release" and not (self.cfg.independent_verification and self.repo is not None):
            return [Post(msg.room, "A release can only be delegated when the clerk verifies releases independently.")]
        if ticket_id != "ANY" and (ticket_id not in self.state.tickets or self.state.tickets[ticket_id].status != "open"):
            return [Post(msg.room, f"{ticket_id} is not an open ticket.")]
        if not (0 <= hh < 24 and 0 <= mm < 60):
            return [Post(msg.room, usage)]
        now = self.now()
        local = region.local_time(now)
        expiry = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if expiry <= local:
            expiry += timedelta(days=1)
        if expiry - local > timedelta(hours=self.cfg.max_standing_order_hours):
            return [Post(msg.room, f"Standing orders last at most {self.cfg.max_standing_order_hours}h.")]
        oid = f"SO-{self.state.next_order}"
        self.state.next_order += 1
        order = StandingOrder(oid, region.key, msg.sender_name, action, "any" if ticket_id == "ANY" else ticket_id,
                              expiry.astimezone(timezone.utc).isoformat(), created_at=now.isoformat())
        self.state.orders[oid] = order
        self.log("standing_order_created", None if order.ticket == "any" else order.ticket, msg.sender_name, region.key,
                 order=oid, action=action, expires_at=order.expires_at)
        return [Post(msg.room,
            f"**{oid}** recorded. While you're away I will sign {order.scope()} on your behalf **only if** "
            f"{order.condition()}: once, until {expiry:%H:%M} {region.label} time. Anything else waits for you. "
            f"It goes in the ledger as your signature under {oid}. Revoke any time with `clerk revoke {oid}`.")]

    def _revoke(self, msg: Incoming, view: RoomView, oid: str) -> list[Post]:
        order = self.state.orders.get(oid)
        if order is None:
            return [Post(msg.room, f"There is no standing order {oid}.")]
        region = self.cfg.regions[order.region]
        if not self._is_person(msg, view) or not self._is_approver(msg.sender_name, region):
            return [Post(msg.room, f"**Refused:** only {region.label}'s approvers can revoke {oid}.")]
        if order.status != "active":
            return [Post(msg.room, f"{oid} is already {order.status}.")]
        order.status = "revoked"
        self.log("standing_order_revoked", None if order.ticket == "any" else order.ticket, msg.sender_name, region.key, order=oid)
        return [Post(msg.room, f"{oid} revoked by {msg.sender_name}.")]

    def _matching_order(self, pending: Pending, region: Region) -> StandingOrder | None:
        now = self.now()
        action = "release" if pending.to == "release" else "handoff"
        if action == "release" and not pending.verified:
            return None
        for order in self.state.orders.values():
            if (order.status == "active" and order.region == region.key and order.action == action
                    and order.ticket in ("any", pending.ticket) and order.uses_left > 0
                    and now < datetime.fromisoformat(order.expires_at)
                    and self._is_approver(order.created_by, region)):
                return order
        return None

    # ------------------------------------------------------------------------------------------ views
    def _custody_card(self, ticket: Ticket) -> str:
        rows = ["| # | From | To | Signed by | Text digest |", "|---|---|---|---|---|"]
        for i, h in enumerate(ticket.history, start=1):
            to = "release" if h["to"] == "release" else self.cfg.regions[h["to"]].label
            rows.append(f"| {i} | {self.cfg.regions[h['from']].label} | {to} | {h['signed_by']} | `{h['digest']}` |")
        check = self.ledger.verify()
        _, head = self.ledger.head()
        entries = self.ledger.for_ticket(ticket.id)
        refusals = sum(1 for e in entries if e["event"] in ("handoff_blocked", "handoff_refused", "approval_refused"))
        delegated = sum(1 for e in entries if e["event"] == "standing_order_used")
        opened = next((e["ts"] for e in entries if e["event"] == "ticket_opened"), None)
        elapsed = f" Open to release: {_span(self.now() - datetime.fromisoformat(opened))}." if opened else ""
        return (f"**Custody card {ticket.id}** for {ticket.customer_token} (released)\n\n" + "\n".join(rows) +
                f"\n\nBorder refusals along the way: {refusals}. Signatures given by standing order while their "
                f"owner was off duty: {delegated}. Personal data that left {ticket.residency}: none.{elapsed}\n"
                f"Ledger: {'intact' if check.ok else 'BROKEN'}, {check.entries} entries, head `{head[:12]}`.")

    def _status(self) -> str:
        open_tickets = [t for t in self.state.tickets.values() if t.status == "open"]
        lines = ["**Desk status**", ""]
        for region in self.cfg.regions.values():
            lines.append(f"- {self._clock_line(region)}")
        lines.append("")
        if not open_tickets:
            lines.append("No open tickets.")
        for t in open_tickets:
            region = self.cfg.regions[t.custody]
            waiting = [p.id for p in self.state.pending.values() if p.ticket == t.id and p.status == "awaiting"]
            lines.append(f"- **{t.id}** {t.customer_token}: custody **{region.label}** (`@{region.role}`)"
                         + (f", awaiting signature: {', '.join(waiting)}" if waiting else ""))
        active = [o for o in self.state.orders.values() if o.status == "active"]
        if active:
            lines.append("")
            lines.append("Standing orders: " + "; ".join(f"{o.id} by {o.created_by}: {o.scope()}" for o in active))
        return "\n".join(lines)

    def _orders_view(self) -> str:
        if not self.state.orders:
            return "No standing orders."
        rows = ["| Order | By | Covers | Until (UTC) | Status |", "|---|---|---|---|---|"]
        for o in self.state.orders.values():
            rows.append(f"| {o.id} | {o.created_by} | {o.scope()} | {o.expires_at[11:16]} | {o.status} |")
        return "\n".join(rows)

    def _ledger_view(self, ticket: str) -> str:
        entries = self.ledger.for_ticket(ticket) if ticket else self.ledger.entries()[-15:]
        if not entries:
            return f"No ledger entries for {ticket or 'this desk'}."
        rows = ["| seq | time (UTC) | event | actor | hash |", "|---|---|---|---|---|"]
        for e in entries:
            rows.append(f"| {e['seq']} | {e['ts'][11:19]} | {e['event']} | {e['actor']} | `{e['hash'][:10]}` |")
        return "\n".join(rows)

    def _verify_ledger(self) -> str:
        check = self.ledger.verify()
        if check.ok:
            _, head = self.ledger.head()
            return f"Ledger intact: {check.entries} entries, chain head `{head[:12]}`."
        return f"**Ledger BROKEN** at entry {check.broken_at}: {check.reason}."

    def _help(self) -> str:
        c = "clerk"  # the plain word avoids the platform's @-mention handling
        return (f"I'm the Customs clerk for `{self.cfg.desk_name}`. People: `{c} open <customer_id> <problem>` (intake), "
                f"`approve H-n` / `reject H-n <reason>`, `{c} standing-order <release|handoff> <TKT-0001|any> until <HH:MM>`, "
                f"`{c} revoke SO-n`, `{c} orders`, `{c} status`, `{c} ledger [TKT-0001]`, `{c} verify-ledger`. "
                f"Agents hand work on with a ```customs-handoff block.")

    # ---------------------------------------------------------------------------------------- helpers
    def _signer(self, pending: Pending) -> Region:
        """Whose signature a crossing needs: the region it leaves, or for a release the release region."""
        return self.cfg.regions[self.cfg.release_region if pending.to == "release" else pending.source]

    def _is_person(self, msg: Incoming, view: RoomView) -> bool:
        return msg.sender_kind == "user" and msg.sender_name not in view.agent_names

    def _is_approver(self, name: str, region: Region) -> bool:
        return _person(name) in {_person(a) for a in region.approvers}

    def _refuse(self, msg: Incoming, region: Region, ticket: str | None, event: str, reason: str) -> list[Post]:
        self.log(event, ticket, msg.sender_name, region.key, reason=reason.splitlines()[0][:200])
        return [Post(msg.room, f"@{msg.sender_name} **Refused:** {reason}")]

    def _holds(self, region: Region | None, ticket: Ticket) -> bool:
        return region is not None and ticket.residency in region.residency

    def _resident_region(self, ticket: Ticket) -> Region | None:
        return next((r for r in self.cfg.regions.values() if ticket.residency in r.residency), None)

    def _clock_line(self, region: Region) -> str:
        now = self.now()
        state = "office open" if region.office_open(now) else "office closed"
        return f"{region.label}: {region.local_time(now):%H:%M} ({state})"

    def _mentions_clerk(self, body: str) -> bool:
        """`@customs-clerk ...` or a message starting with the word `clerk`. The plain word avoids the chat
        platform's addressing machinery entirely (no mention, nothing for Switch to auto-answer)."""
        return f"@{self.cfg.clerk_name}".lower() in body.lower() or re.match(r"^\s*clerk\b", body, re.IGNORECASE) is not None

    def _strip_mention(self, body: str) -> str:
        body = re.sub(rf"@{re.escape(self.cfg.clerk_name)}\b[:,]?\s*", "", body, flags=re.IGNORECASE)
        return re.sub(r"^\s*clerk\b[:,]?\s*", "", body, flags=re.IGNORECASE).strip()
