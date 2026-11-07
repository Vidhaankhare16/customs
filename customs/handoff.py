"""The handoff an agent writes when work leaves its region, and the clerk's validation of it.

Agents put one fenced block in a chat message:

    ```customs-handoff
    {
      "ticket": "TKT-0001",
      "to": "eu",
      "summary": "Totals used float arithmetic; switched to Decimal with half-up rounding.",
      "done": ["Reproduced the cent differences from the case file", "Fixed rounding"],
      "next": ["Reconcile against the customer's real invoices"],
      "evidence": ["pytest: 9 passed", "reproduced [INV-1] 312,58 -> 312,59"],
      "branch": "fix/tkt-0001-rounding",
      "commit": "3f9c2ab",
      "could_not_access": ["Real invoices (EU resident)"],
      "questions": []
    }
    ```

`to` is a region key, or "release" when the resident region asks to ship.
Everything is checked; nothing is guessed. Errors are returned as plain sentences the agent can act on.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

BLOCK = re.compile(r"```customs-handoff\s*\n(.*?)\n?```", re.DOTALL)
TICKET = re.compile(r"^TKT-\d{4}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
TEXT_FIELDS = ("summary",)
LIST_FIELDS = ("done", "next", "evidence", "could_not_access", "questions")
REQUIRED_LISTS = ("done", "next", "evidence")
ALLOWED = {"ticket", "to", "branch", "commit", *TEXT_FIELDS, *LIST_FIELDS}
MAX_ITEM = 500
MAX_ITEMS = 12


@dataclass
class Handoff:
    ticket: str
    to: str
    summary: str
    done: list[str]
    next: list[str]
    evidence: list[str]
    branch: str | None = None
    commit: str | None = None
    could_not_access: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def fields(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            **{name: getattr(self, name) for name in LIST_FIELDS},
        }

    def texts(self) -> list[tuple[str, str]]:
        """(location, text) for every free-text value, for the border scan."""
        out = [("summary", self.summary)]
        for name in LIST_FIELDS:
            out += [(f"{name}[{i}]", item) for i, item in enumerate(getattr(self, name))]
        return out

    def map_texts(self, fn) -> "Handoff":
        return Handoff(
            ticket=self.ticket,
            to=self.to,
            summary=fn(self.summary),
            done=[fn(x) for x in self.done],
            next=[fn(x) for x in self.next],
            evidence=[fn(x) for x in self.evidence],
            branch=self.branch,
            commit=self.commit,
            could_not_access=[fn(x) for x in self.could_not_access],
            questions=[fn(x) for x in self.questions],
        )

    def to_json(self) -> dict:
        return {
            "ticket": self.ticket,
            "to": self.to,
            "summary": self.summary,
            "done": self.done,
            "next": self.next,
            "evidence": self.evidence,
            "branch": self.branch,
            "commit": self.commit,
            "could_not_access": self.could_not_access,
            "questions": self.questions,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Handoff":
        return cls(**data)

    def render(self) -> str:
        """Markdown for the receiving room."""
        parts = [f"**Summary:** {self.summary}"]
        if self.branch:
            parts.append(f"**Code:** branch `{self.branch}` at commit `{self.commit}`")
        for title, items in (
            ("Done", self.done),
            ("Your next steps", self.next),
            ("Evidence", self.evidence),
            ("Could not access", self.could_not_access),
            ("Open questions", self.questions),
        ):
            if items:
                parts.append(f"**{title}:**\n" + "\n".join(f"- {item}" for item in items))
        return "\n\n".join(parts)


def extract(body: str) -> str | None:
    match = BLOCK.search(body)
    return match.group(1) if match else None


def parse(body: str) -> tuple[Handoff | None, list[str]]:
    """Parse the handoff block in a message. Returns (handoff, errors); errors empty when valid."""
    raw = extract(body)
    if raw is None:
        return None, ["no ```customs-handoff block found"]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"the handoff block is not valid JSON ({exc.msg} at line {exc.lineno})"]
    if not isinstance(data, dict):
        return None, ["the handoff block must be a JSON object"]

    errors: list[str] = []
    unknown = sorted(set(data) - ALLOWED)
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    ticket = data.get("ticket")
    if not isinstance(ticket, str) or not TICKET.match(ticket):
        errors.append('"ticket" must look like TKT-0001')
    to = data.get("to")
    if not isinstance(to, str) or not to:
        errors.append('"to" must name a region or "release"')
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append('"summary" must be a non-empty string')
    elif len(summary) > 2 * MAX_ITEM:
        errors.append(f'"summary" is longer than {2 * MAX_ITEM} characters')
    lists: dict[str, list[str]] = {}
    for name in LIST_FIELDS:
        value = data.get(name, [])
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            errors.append(f'"{name}" must be a list of strings')
            continue
        value = [x.strip() for x in value if x.strip()]
        if name in REQUIRED_LISTS and not value:
            errors.append(f'"{name}" needs at least one item')
        if len(value) > MAX_ITEMS:
            errors.append(f'"{name}" has more than {MAX_ITEMS} items')
        if any(len(x) > MAX_ITEM for x in value):
            errors.append(f'an item in "{name}" is longer than {MAX_ITEM} characters')
        lists[name] = value
    branch, commit = data.get("branch"), data.get("commit")
    if branch is not None and (not isinstance(branch, str) or not BRANCH.match(branch)):
        errors.append('"branch" must be a plain branch name')
    if commit is not None and (not isinstance(commit, str) or not COMMIT.match(commit)):
        errors.append('"commit" must be a lowercase git commit hash (7-40 hex characters)')
    if (branch is None) != (commit is None):
        errors.append('"branch" and "commit" go together: give both or neither')
    if errors:
        return None, errors
    return (
        Handoff(
            ticket=ticket,
            to=to,
            summary=summary.strip(),
            done=lists["done"],
            next=lists["next"],
            evidence=lists["evidence"],
            branch=branch,
            commit=commit,
            could_not_access=lists.get("could_not_access", []),
            questions=lists.get("questions", []),
        ),
        [],
    )
