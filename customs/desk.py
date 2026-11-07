"""The clerk's decisions, as a pure state machine.

`Desk.handle(message, view)` takes one room message plus a snapshot of who is in the room and who holds which
role, and returns the posts the clerk should make. It does no I/O of its own: the Switch client, the clock,
the vault and git are injected, so every rule here is unit-tested without a server.

The rules, in one place:

* A ticket is always in the custody of exactly one region. Only the agent holding that region's role may hand
  it on, and only along a configured route.
* Text leaving a data-resident region for one that isn't must contain no personal data. If it does, the
  handoff is blocked (not repaired) and the author told where. Identifiers are pseudonymised on the way out
  and re-identified only on the way back in.
* Every handoff needs a person's approval from the region the work is leaving, pinned to the digest of the
  exact text that will cross. Agents cannot approve. Approvals are single-use.
* A release is re-verified independently by the clerk at the exact commit, approved by a person in the
  resident region, and only that commit is merged.
* Every decision, including every refusal, is written to the hash-chained ledger.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from customs import handoff as handoff_mod
from customs.config import Config, Region
from customs.ledger import Ledger
from customs.redact import Border, Pseudonyms

APPROVAL = re.compile(r"^\s*(approve|reject)\s+(H-\d+)\b(.*)$", re.IGNORECASE | re.DOTALL)


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


@dataclass
class State:
    tickets: dict[str, Ticket] = field(default_factory=dict)
    pending: dict[str, Pending] = field(default_factory=dict)
    pseudonyms: Pseudonyms = field(default_factory=Pseudonyms)
    next_ticket: int = 1
    next_handoff: int = 1

    def to_json(self) -> dict:
        return {
            "tickets": {k: vars(v) for k, v in self.tickets.items()},
            "pending": {k: vars(v) for k, v in self.pending.items()},
            "pseudonyms": self.pseudonyms.to_json(),
            "next_ticket": self.next_ticket,
            "next_handoff": self.next_handoff,
        }

    @classmethod
    def from_json(cls, data: dict | None) -> "State":
        data = data or {}
        return cls(
            tickets={k: Ticket(**v) for k, v in data.get("tickets", {}).items()},
            pending={k: Pending(**v) for k, v in data.get("pending", {}).items()},
            pseudonyms=Pseudonyms.from_json(data.get("pseudonyms")),
            next_ticket=data.get("next_ticket", 1),
            next_handoff=data.get("next_handoff", 1),
        )


def _person(name: str) -> str:
    """Chat platforms spell the same person '@Berlin-Lead' or 'berlin-lead'; compare them as one."""
    return name.strip().lstrip("@").casefold()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


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
        self.now = now

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
        command = command.lower().strip()
        if command == "open":
            return self._open(msg, args.strip())
        if command == "status":
            return [Post(msg.room, self._status())]
        if command == "ledger":
            return [Post(msg.room, self._ledger_view(args.strip().upper()))]
        if command in ("verify-ledger", "verify"):
            return [Post(msg.room, self._verify_ledger())]
        return [Post(msg.room, self._help())]

    # ------------------------------------------------------------------------------------------ open
    def _open(self, msg: Incoming, args: str) -> list[Post]:
        if msg.room != self.cfg.intake_room:
            return [Post(msg.room, f"Tickets are opened in `{self.cfg.intake_room}`.")]
        if msg.sender_kind != "user":
            self.ledger.append("open_refused", None, msg.sender_name, reason="sender is not a person")
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
        self.ledger.append("ticket_opened", tid, msg.sender_name, None, customer=token, residency=ticket.residency)
        self.ledger.append("custody_transferred", tid, self.cfg.clerk_name, start.key, to=start.key)
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
            Post(self.cfg.intake_room, f"**{tid}** opened for {token} ({ticket.residency} data). {self._clock_line(start)}"),
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
            return self._refuse(msg, source, None, "handoff_refused", "the handoff is not valid:\n- " + "\n- ".join(errors))
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
                self.ledger.append(
                    "handoff_blocked", ticket.id, msg.sender_name, source.key, to=dest.key,
                    findings=[f"{f.category}@{f.location}" for f in findings],
                )
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

        approvers = self.cfg.regions[self.cfg.release_region].approvers if release else source.approvers
        if release and self.cfg.independent_verification and self.repo is not None:
            ok, summary = self.repo.verify(parsed.commit)
            self.ledger.append("independent_verification", ticket.id, self.cfg.clerk_name, source.key,
                               commit=parsed.commit, passed=ok)
            if not ok:
                return [Post(msg.room,
                    f"@{msg.sender_name} **Release refused.** I reconciled commit `{parsed.commit}` myself and it "
                    f"does not pass:\n```\n{summary}\n```\nNothing ships until it does.")]
            pending.verification = summary

        self.state.pending[pid] = pending
        self.ledger.append("handoff_filed", ticket.id, msg.sender_name, source.key, handoff=pid,
                           to=pending.to, digest=pending.digest, commit=parsed.commit)
        mention = " ".join(f"@{a}" for a in approvers)
        crossing = f"This exact text goes to `{dest.room}`:" if dest else "This is what you are approving:"
        verified = f"\n\nIndependent check by the clerk at `{parsed.commit}`:\n```\n{pending.verification}\n```" if pending.verification else ""
        return [Post(msg.room,
            f"{mention} **{pid}** passed the border check and needs your signature.{verified}\n\n"
            f"{crossing} (digest `{pending.digest}`)\n\n> " + outbound.replace("\n", "\n> ") +
            f"\n\nReply `approve {pid}` or `reject {pid} <reason>`.")]

    # -------------------------------------------------------------------------------------- approval
    def _decide(self, msg: Incoming, view: RoomView, pid: str, approve: bool, reason: str) -> list[Post]:
        pending = self.state.pending.get(pid)
        if pending is None:
            return [Post(msg.room, f"There is no handoff {pid}.")]
        if pending.status != "awaiting":
            return [Post(msg.room, f"{pid} was already {pending.status}. Approvals are single-use.")]
        ticket = self.state.tickets[pending.ticket]
        source = self.cfg.regions[pending.source]
        release = pending.to == "release"
        signing_region = self.cfg.regions[self.cfg.release_region] if release else source
        if msg.room != signing_region.room:
            return [Post(msg.room, f"{pid} is signed in `{signing_region.room}`.")]
        if msg.sender_kind != "user" or msg.sender_name in view.agent_names:
            self.ledger.append("approval_refused", ticket.id, msg.sender_name, source.key, handoff=pid, reason="sender is not a person")
            return [Post(msg.room, f"**Refused:** {pid} must be signed by a person, and `{msg.sender_name}` is not one. Logged.")]
        if _person(msg.sender_name) not in {_person(a) for a in signing_region.approvers}:
            self.ledger.append("approval_refused", ticket.id, msg.sender_name, source.key, handoff=pid, reason="not an approver")
            return [Post(msg.room, f"**Refused:** `{msg.sender_name}` is not an approver for {signing_region.label} "
                                   f"(approvers: {', '.join(signing_region.approvers)}). Logged.")]

        if not approve:
            pending.status = "rejected"
            self.ledger.append("handoff_rejected", ticket.id, msg.sender_name, source.key, handoff=pid, reason=reason or "-")
            return [Post(msg.room, f"@{pending.author} {pid} rejected by {msg.sender_name}: {reason or 'no reason given'}. "
                                   f"{ticket.id} stays with {source.label}.")]

        pending.status = "approved"
        self.ledger.append("handoff_approved", ticket.id, msg.sender_name, source.key, handoff=pid, digest=pending.digest)
        if release:
            return self._release(msg, ticket, pending)

        dest = self.cfg.regions[pending.to]
        ticket.custody = dest.key
        ticket.history.append({"from": source.key, "to": dest.key, "signed_by": msg.sender_name,
                               "digest": pending.digest, "at": self.now().isoformat(timespec="seconds")})
        self.ledger.append("custody_transferred", ticket.id, self.cfg.clerk_name, dest.key, to=dest.key, handoff=pid)
        return [
            Post(dest.room, f"@{dest.role} **{ticket.id}** is now in your custody, signed out of {source.label} "
                            f"by {msg.sender_name}.\n\n{pending.outbound}"),
            Post(msg.room, f"{pid} approved. {ticket.id} is now with {dest.label}. {self._clock_line(dest)}"),
            Post(self.cfg.intake_room, f"**{ticket.id}**: {source.label} -> {dest.label}, signed by {msg.sender_name}. "
                                       f"{self._clock_line(dest)}"),
        ]

    def _release(self, msg: Incoming, ticket: Ticket, pending: Pending) -> list[Post]:
        handoff = pending.handoff
        if self.repo is None:
            ok, detail = False, "no origin repository is configured"
        else:
            ok, detail = self.repo.merge(handoff["commit"], handoff["branch"])
        if not ok:
            self.ledger.append("release_failed", ticket.id, self.cfg.clerk_name, pending.source, detail=detail)
            return [Post(msg.room, f"Release of {ticket.id} failed: {detail}")]
        ticket.status = "released"
        ticket.history.append({"from": pending.source, "to": "release", "signed_by": msg.sender_name,
                               "digest": pending.digest, "at": self.now().isoformat(timespec="seconds")})
        self.ledger.append("released", ticket.id, self.cfg.clerk_name, pending.source, commit=handoff["commit"], detail=detail)
        card = self._custody_card(ticket)
        return [Post(msg.room, f"**{ticket.id} released.** {detail}"), Post(self.cfg.intake_room, card)]

    # ------------------------------------------------------------------------------------------ views
    def _custody_card(self, ticket: Ticket) -> str:
        rows = ["| # | From | To | Signed by | Text digest |", "|---|---|---|---|---|"]
        for i, h in enumerate(ticket.history, start=1):
            to = "release" if h["to"] == "release" else self.cfg.regions[h["to"]].label
            rows.append(f"| {i} | {self.cfg.regions[h['from']].label} | {to} | {h['signed_by']} | `{h['digest']}` |")
        check = self.ledger.verify()
        _, head = self.ledger.head()
        blocked = sum(1 for e in self.ledger.for_ticket(ticket.id) if e["event"] in ("handoff_blocked", "handoff_refused", "approval_refused"))
        return (f"**Custody card {ticket.id}** for {ticket.customer_token} (released)\n\n" + "\n".join(rows) +
                f"\n\nBorder refusals along the way: {blocked}. Personal data that left {ticket.residency}: none.\n"
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
        return "\n".join(lines)

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
        c = self.cfg.clerk_name
        return (f"I'm the Customs clerk for `{self.cfg.desk_name}`. Commands: `@{c} open <customer_id> <problem>` (intake), "
                f"`@{c} status`, `@{c} ledger [TKT-0001]`, `@{c} verify-ledger`. Agents hand work on with a "
                f"```customs-handoff block; people sign with `approve H-n` / `reject H-n <reason>`.")

    # ---------------------------------------------------------------------------------------- helpers
    def _refuse(self, msg: Incoming, region: Region, ticket: str | None, event: str, reason: str) -> list[Post]:
        self.ledger.append(event, ticket, msg.sender_name, region.key, reason=reason.splitlines()[0][:200])
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
        return f"@{self.cfg.clerk_name}".lower() in body.lower()

    def _strip_mention(self, body: str) -> str:
        return re.sub(rf"@{re.escape(self.cfg.clerk_name)}\b[:,]?\s*", "", body, flags=re.IGNORECASE).strip()
