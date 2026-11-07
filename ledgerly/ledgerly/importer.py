"""CSV import of customer invoices (recurring orders exported from the customer's ERP)."""

from __future__ import annotations

import csv
from pathlib import Path

from ledgerly.invoice import Invoice, Line


def parse_amount(text: str) -> float:
    """Parse an amount as the customer's export writes it (e.g. "12,50")."""
    return float(text.strip().replace(",", "."))


def import_csv(path: str | Path) -> list[Invoice]:
    """Read invoices from a semicolon-separated export.

    Columns used: invoice_no, customer_id, description, quantity, unit_price, vat_rate (percent).
    Other columns (contact details, bank data) are ignored by the importer.
    """
    invoices: dict[str, Invoice] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            invoice = invoices.setdefault(
                row["invoice_no"], Invoice(row["invoice_no"], row["customer_id"])
            )
            try:
                line = Line(
                    description=row["description"],
                    quantity=parse_amount(row["quantity"]),
                    unit_price=parse_amount(row["unit_price"]),
                    vat_rate=parse_amount(row["vat_rate"]) / 100,
                )
            except ValueError:
                continue  # TODO: malformed rows from old exports
            invoice.lines.append(line)
    return list(invoices.values())
