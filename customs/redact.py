"""The border check: what personal data looks like, and how identifiers are pseudonymised.

Two kinds of resident data are treated differently:

* **Personal data** (people's names, emails, phone numbers, IBANs, VAT IDs, street addresses). Text an agent
  writes must not contain any of it when it crosses a border. The clerk does not quietly fix an agent that
  tried to export it: it blocks the handoff, says where the problem is (never what the value was) and asks
  for a rewrite. Text the clerk itself composes (the case file) is scrubbed to tokens.
* **Identifiers** (invoice numbers, the customer's company name). Engineers need to refer to "the failing
  invoice", so identifiers are pseudonymised on the way out ([INV-3]) and re-identified only on the way back
  into the resident region. The mapping never leaves the clerk.

Detection is deterministic: exact matches against the customer registry, plus patterns for things the
registry doesn't know about. Ambiguity fails closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"),
    "phone": re.compile(r"\+\d{1,3}(?:[ \-/]?\(?\d{1,5}\)?){2,6}"),
    "vat_id": re.compile(r"\b(?:ATU|BE0|DE|DK|ES[A-Z0-9]|FI|FR[A-Z0-9]{2}|IE|IT|LU|NL|PL|PT|SE)\d{7,12}(?:B\d{2})?\b"),
}


@dataclass(frozen=True)
class Finding:
    category: str  # "email", "person_name", ...
    location: str  # where it was found, e.g. "next[1]" (never the value)


@dataclass
class Pseudonyms:
    """Identifier <-> token mapping. Lives only with the clerk, inside the resident region."""

    forward: dict[str, str] = field(default_factory=dict)  # "BL-2026-0101" -> "[INV-1]"
    counters: dict[str, int] = field(default_factory=dict)

    def token(self, kind: str, value: str) -> str:
        if value not in self.forward:
            self.counters[kind] = self.counters.get(kind, 0) + 1
            self.forward[value] = f"[{kind}-{self.counters[kind]}]"
        return self.forward[value]

    def reverse(self) -> dict[str, str]:
        return {tok: val for val, tok in self.forward.items()}

    def to_json(self) -> dict:
        return {"forward": self.forward, "counters": self.counters}

    @classmethod
    def from_json(cls, data: dict | None) -> "Pseudonyms":
        data = data or {}
        return cls(dict(data.get("forward", {})), dict(data.get("counters", {})))


@dataclass(frozen=True)
class Registry:
    """What the resident region knows about its customers' data."""

    personal: dict[str, tuple[str, ...]]  # category -> exact strings
    identifiers: dict[str, tuple[str, ...]]  # token kind -> exact strings, e.g. {"CUSTOMER": ("Brauhaus ...",)}
    identifier_patterns: dict[str, re.Pattern[str]]  # token kind -> pattern, e.g. {"INV": BL-\d{4}-\d{4}}

    @classmethod
    def from_customer(cls, customer: dict, invoice_pattern: str) -> "Registry":
        names, emails, phones = [], [], []
        for contact in customer.get("contacts", []):
            names.append(contact["name"])
            emails.append(contact["email"])
            phones.append(contact["phone"])
        personal = {
            "person_name": tuple(names),
            "email": tuple(emails),
            "phone": tuple(phones),
            "iban": tuple(filter(None, [customer.get("iban")])),
            "vat_id": tuple(filter(None, [customer.get("vat_id")])),
            "address": tuple(filter(None, [customer.get("street"), customer.get("postcode_city")])),
        }
        identifiers = {"CUSTOMER": tuple(filter(None, [customer.get("legal_name")]))}
        return cls(personal, identifiers, {"INV": re.compile(invoice_pattern)})


class Border:
    def __init__(self, registries: list[Registry], pseudonyms: Pseudonyms):
        self.registries = registries
        self.pseudonyms = pseudonyms

    # -- detection ---------------------------------------------------------------------------------------
    def find_personal(self, text: str, location: str = "text") -> list[Finding]:
        found: list[Finding] = []
        lowered = text.casefold()
        for registry in self.registries:
            for category, values in registry.personal.items():
                for value in values:
                    if _contains(lowered, value):
                        found.append(Finding(category, location))
                    # names also leak as their parts ("Jana", "Wolff"); surnames are what identify
                    if category == "person_name":
                        surname = value.split()[-1]
                        if len(surname) >= 4 and _contains_word(text, surname):
                            found.append(Finding(category, location))
        for category, pattern in PATTERNS.items():
            if pattern.search(text):
                found.append(Finding(category, location))
        return _dedupe(found)

    # -- outbound (leaving the resident region) ---------------------------------------------------------
    def pseudonymise(self, text: str) -> str:
        for registry in self.registries:
            for kind, values in registry.identifiers.items():
                for value in sorted(values, key=len, reverse=True):
                    text = re.sub(re.escape(value), self.pseudonyms.token(kind, value), text, flags=re.IGNORECASE)
            for kind, pattern in registry.identifier_patterns.items():
                text = pattern.sub(lambda m, k=kind: self.pseudonyms.token(k, m.group(0)), text)
        return text

    def scrub(self, text: str) -> str:
        """For text the clerk composes from resident data: every personal value becomes a token."""
        text = self.pseudonymise(text)
        for registry in self.registries:
            for category, values in registry.personal.items():
                for value in sorted(values, key=len, reverse=True):
                    text = re.sub(re.escape(value), f"[{category.upper()}]", text, flags=re.IGNORECASE)
        for category, pattern in PATTERNS.items():
            text = pattern.sub(f"[{category.upper()}]", text)
        return text

    # -- inbound (arriving in the resident region) ------------------------------------------------------
    def reidentify(self, text: str) -> str:
        reverse = self.pseudonyms.reverse()
        return re.sub(r"\[[A-Z]+-\d+\]", lambda m: reverse.get(m.group(0), m.group(0)), text)


def _contains(lowered_text: str, value: str) -> bool:
    return value.casefold() in lowered_text or _squash(value) in _squash(lowered_text)


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, flags=re.IGNORECASE) is not None


def _squash(value: str) -> str:
    """Ignore spacing/punctuation so 'DE44 5001 ...' and 'DE4450010...' match."""
    return re.sub(r"[\s\-./()]", "", value.casefold())


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen, out = set(), []
    for f in findings:
        if (f.category, f.location) not in seen:
            seen.add((f.category, f.location))
            out.append(f)
    return out
