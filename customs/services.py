"""The clerk's side of the world: the customer vault and the shared git origin.

The clerk is the border, so it runs inside the data-resident region and may read the vault. It never posts
vault contents anywhere without passing them through `Border.scrub` first.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from customs.redact import Border, Registry

INVOICE_PATTERN = r"BL-\d{4}-\d{4}"


class VaultCaseFiles:
    def __init__(self, vault: Path, invoice_pattern: str = INVOICE_PATTERN):
        self.vault = Path(vault)
        self.invoice_pattern = invoice_pattern

    def _customers(self) -> dict[str, dict]:
        data = json.loads((self.vault / "customer.json").read_text(encoding="utf-8"))
        customers = data if isinstance(data, list) else [data]
        return {c["customer_id"]: c for c in customers}

    def customer(self, customer_id: str) -> dict | None:
        return self._customers().get(customer_id)

    def registries(self) -> list[Registry]:
        return [Registry.from_customer(c, self.invoice_pattern) for c in self._customers().values()]

    def case_file(self, customer_id: str, border: Border) -> str:
        """The customer's complaint and the line items of the invoices it names, scrubbed for export."""
        import re

        complaint = (self.vault / "complaint.txt").read_text(encoding="utf-8")
        named = list(dict.fromkeys(re.findall(self.invoice_pattern, complaint)))
        with open(self.vault / "invoices.csv", encoding="utf-8") as handle:
            rows = [r for r in csv.DictReader(handle, delimiter=";") if r["customer_id"] == customer_id]
        with open(self.vault / "customer_totals.csv", encoding="utf-8") as handle:
            books = {r["invoice_no"]: r["gross"] for r in csv.DictReader(handle, delimiter=";")}

        parts = ["**Case file** (pseudonymised by the clerk; personal data removed)", "", "Customer's message:",
                 "```", border.scrub(complaint.split("\n\n", 1)[-1]).strip(), "```", "",
                 "Line items of the invoices the customer named (quantity; unit price; VAT %):"]
        for number in named:
            token = border.pseudonymise(number)
            parts.append(f"\n{token} (customer's books: {books.get(number, '?')} EUR)")
            parts.append("```")
            for r in rows:
                if r["invoice_no"] == number:
                    parts.append(f"{r['description']}; {r['quantity']}; {r['unit_price']}; {r['vat_rate']}")
            parts.append("```")
        parts.append(f"\nThe full export has {len({r['invoice_no'] for r in rows})} invoices; it stays in the resident region.")
        return "\n".join(parts)


class GitOrigin:
    """The team's shared repository (a bare repo standing in for GitHub)."""

    def __init__(self, origin: Path, vault: Path | None, verify_command: tuple[str, ...], main: str = "main"):
        self.origin = Path(origin)
        self.vault = vault
        self.verify_command = verify_command
        self.main = main

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", f"--git-dir={self.origin}", *args], capture_output=True, text=True, check=check)

    def commit_exists(self, commit: str) -> bool:
        return self._git("cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0

    def resolve(self, commit: str) -> str:
        return self._git("rev-parse", f"{commit}^{{commit}}").stdout.strip()

    def verify(self, commit: str) -> tuple[bool, str]:
        """Reconcile the exact commit against the vault in a fresh export, not in anyone's working copy."""
        if not self.verify_command or self.vault is None:
            return False, "no verification command is configured"
        tmp = Path(tempfile.mkdtemp(prefix="customs-verify-"))
        try:
            archive = tmp / "src.zip"
            self._git("archive", "--format=zip", "-o", str(archive), self.resolve(commit))
            checkout = tmp / "src"
            with zipfile.ZipFile(archive) as z:
                z.extractall(checkout)
            argv = [part.format(checkout=checkout, vault=self.vault, python=sys.executable) for part in self.verify_command]
            run = subprocess.run(argv, capture_output=True, text=True, timeout=300)
            output = (run.stdout + run.stderr).strip()[-1500:]
            return run.returncode == 0, output or f"exit code {run.returncode}"
        except (subprocess.SubprocessError, OSError) as exc:
            return False, f"verification could not run: {exc}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def merge(self, commit: str, branch: str) -> tuple[bool, str]:
        """Fast-forward main to exactly this commit, or refuse. Atomic: fails if main moved meanwhile."""
        full = self.resolve(commit)
        current = self._git("rev-parse", self.main).stdout.strip()
        if self._git("merge-base", "--is-ancestor", current, full, check=False).returncode != 0:
            return False, f"`{commit}` is not a fast-forward of {self.main}; rebase `{branch}` on {self.main} first."
        updated = self._git("update-ref", f"refs/heads/{self.main}", full, current, check=False)
        if updated.returncode != 0:
            return False, f"{self.main} moved while releasing; try again."
        return True, f"`{self.main}` fast-forwarded to `{full[:10]}` (exactly the verified, approved commit)."
