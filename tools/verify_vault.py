"""Reconcile a Ledgerly checkout against the customer's real invoices. EU-only tool.

Runs the checkout's own importer and totals over the customer's export, compares every invoice with the
customer's books, and checks that every exported row became an invoice line.

The full report names invoices and is written inside the EU workspace. Only the summary printed
to stdout is meant for the room, and even that passes the Customs clerk's border check before it leaves the EU.

Usage:  python verify_vault.py --repo <ledgerly checkout> --vault <vault dir> [--report report.json]
Exit code 0 when every invoice reconciles, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

CENT = Decimal("0.01")


def german_amount(text: str) -> Decimal:
    return Decimal(text.replace(".", "").replace(",", "."))


def as_cents(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


def shape(text: str) -> str:
    """'1.234,50' -> 'd.ddd,dd': the format of a value without the value."""
    return "".join("d" if ch.isdigit() else ch for ch in text)


def reconcile(repo: Path, vault: Path) -> dict:
    sys.path.insert(0, str(repo))
    for name in [m for m in sys.modules if m == "ledgerly" or m.startswith("ledgerly.")]:
        del sys.modules[name]
    ledgerly = importlib.import_module("ledgerly")

    with open(vault / "customer_totals.csv", encoding="utf-8") as handle:
        books = {row["invoice_no"]: german_amount(row["gross"]) for row in csv.DictReader(handle, delimiter=";")}
    with open(vault / "invoices.csv", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle, delimiter=";"))
    rows_per_invoice = Counter(row["invoice_no"] for row in raw_rows)

    result = {"invoices": len(books), "reconciled": 0, "mismatches": []}
    try:
        imported = {inv.number: inv for inv in ledgerly.import_csv(vault / "invoices.csv")}
    except Exception as exc:  # an importer that raises is a finding, not a crash of this tool
        result["import_error"] = f"{type(exc).__name__}: {exc}"
        return result

    for number, expected in books.items():
        invoice = imported.get(number)
        finding = {"invoice": number, "expected_gross": str(expected)}
        if invoice is None:
            finding.update(kind="missing_invoice")
            result["mismatches"].append(finding)
            continue
        try:
            got = as_cents(ledgerly.totals(invoice)["gross"])
        except (InvalidOperation, ValueError, TypeError) as exc:
            finding.update(kind="totals_error", error=str(exc))
            result["mismatches"].append(finding)
            continue
        dropped = rows_per_invoice[number] - len(invoice.lines)
        if got == expected and dropped == 0:
            result["reconciled"] += 1
            continue
        finding.update(got_gross=str(got), diff=str(got - expected), rows_in_export=rows_per_invoice[number],
                       lines_imported=len(invoice.lines))
        if dropped:
            finding["kind"] = "rows_dropped_on_import"
            finding["dropped_row_shapes"] = _rejected_shapes(ledgerly, [r for r in raw_rows if r["invoice_no"] == number])
        else:
            finding["kind"] = "cent_difference" if abs(got - expected) <= Decimal("0.05") else "amount_difference"
        result["mismatches"].append(finding)
    return result


def _rejected_shapes(ledgerly, rows: list[dict]) -> list[str]:
    """Formats of the values the checkout's amount parser rejects (formats only, never the values)."""
    parse = getattr(getattr(ledgerly, "importer", None), "parse_amount", None)
    shapes = set()
    for row in rows:
        for column in ("quantity", "unit_price", "vat_rate"):
            if parse is None:
                shapes.add(f"{column}={shape(row[column])}")
                continue
            try:
                parse(row[column])
            except Exception:  # noqa: BLE001 - any rejection is what we are looking for
                shapes.add(f"{column}={shape(row[column])}")
    return sorted(shapes)


def summary(result: dict) -> str:
    if "import_error" in result:
        return f"RECONCILIATION FAILED: importer raised {result['import_error']}"
    kinds = Counter(m["kind"] for m in result["mismatches"])
    lines = [f"Reconciled {result['reconciled']}/{result['invoices']} invoices against the customer's books."]
    for kind, count in sorted(kinds.items()):
        lines.append(f"- {count} x {kind}")
    shapes = sorted({s for m in result["mismatches"] for s in m.get("dropped_row_shapes", [])})
    if shapes:
        lines.append("Dropped rows had these value formats (formats only, no values): " + "; ".join(shapes))
    diffs = sorted({m["diff"] for m in result["mismatches"] if m["kind"] == "cent_difference"})
    if diffs:
        lines.append("Cent differences seen: " + ", ".join(diffs))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--report", type=Path, help="write the full (EU-only) report here")
    args = parser.parse_args()
    result = reconcile(args.repo.resolve(), args.vault.resolve())
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(summary(result))
    ok = "import_error" not in result and not result["mismatches"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
