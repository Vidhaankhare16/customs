"""Generate the synthetic EU customer vault used by the Customs demo.

Everything here is FAKE: the company, the people, the bank details and the invoices. It is generated
so that the demo is reproducible, and so that the data has the shape real customer data has: personal
data (names, emails, phone numbers, IBAN, VAT ID, address) next to ordinary business amounts.

The customer's own totals ("customer_totals.csv") are computed with the rules in ledgerly/SPEC.md,
using exact decimal arithmetic. They are the ground truth the EU verifier reconciles against.

Usage:  python fixtures/generate_vault.py [--out fixtures/eu-vault] [--seed 7]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

CENT = Decimal("0.01")

CUSTOMER = {
    "customer_id": "C-DE-0042",
    "legal_name": "Brauhaus Lindenhof GmbH",
    "residency": "EU",
    "contacts": [
        {"name": "Jana Wolff", "email": "jana.wolff@brauhaus-lindenhof.de", "phone": "+49 30 5557 0142"},
        {"name": "Tobias Brenner", "email": "t.brenner@brauhaus-lindenhof.de", "phone": "+49 30 5557 0199"},
    ],
    "vat_id": "DE298765431",
    "iban": "DE44 5001 0517 5407 3249 31",
    "street": "Lindenstraße 17",
    "postcode_city": "10969 Berlin",
}

# (description, unit price, vat rate %). Food at the reduced rate, everything else at the standard rate.
CATALOGUE = [
    ("Hopfen Hallertauer Tradition (kg)", "18.35", 7),
    ("Gerstenmalz Pilsner (kg)", "1.335", 7),
    ("Weizenmalz hell (kg)", "1.415", 7),
    ("Brauhefe W-34/70 (Pack)", "6.45", 7),
    ("Etiketten Rolle 1000 Stk", "38.90", 19),
    ("Kronkorken 26mm (1000 Stk)", "21.15", 19),
    ("Reinigungsmittel CIP (10 l)", "64.95", 19),
    ("Fasswartung (Stunde)", "72.50", 19),
    ("Lieferpauschale", "14.90", 19),
]
BIG_ITEMS = [
    ("Gärtank Edelstahl 500 l", "2489.00", 19),
    ("Abfüllanlage Wartungsvertrag (Jahr)", "1349.50", 19),
]
QUANTITIES = ["1", "2", "3", "5", "12", "25", "0.5", "1.5", "2.5", "7.5", "12.5", "37.5"]


def round_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def reference_totals(lines: list[tuple[str, Decimal, Decimal, int]]) -> dict[str, Decimal]:
    """Totals per ledgerly/SPEC.md, in exact decimal arithmetic."""
    net = vat = Decimal("0")
    for _desc, qty, price, rate in lines:
        line_net = round_cents(qty * price)
        net += line_net
        vat += round_cents(line_net * Decimal(rate) / Decimal(100))
    return {"net": net, "vat": vat, "gross": net + vat}


def german(value: Decimal, places: int = 2) -> str:
    """Format like a German ERP export: 1.234,56."""
    text = f"{value:,.{places}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def german_qty(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


def generate(out: Path, seed: int, invoices: int = 40, big_invoices: int = 2) -> dict:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    big_slots = set(rng.sample(range(invoices), big_invoices))

    rows, totals_rows, all_invoices = [], [], []
    for i in range(invoices):
        number = f"BL-2026-{101 + i:04d}"
        contact = CUSTOMER["contacts"][i % 2]
        credit_note = i % 13 == 12
        lines = []
        for _ in range(rng.randint(1, 4)):
            desc, price, rate = rng.choice(CATALOGUE)
            qty = Decimal(rng.choice(QUANTITIES))
            lines.append((desc, -qty if credit_note else qty, Decimal(price), rate))
        if i in big_slots:
            desc, price, rate = rng.choice(BIG_ITEMS)
            lines.append((desc, Decimal("1"), Decimal(price), rate))
        for desc, qty, price, rate in lines:
            rows.append(
                {
                    "invoice_no": number,
                    "customer_id": CUSTOMER["customer_id"],
                    "customer_name": CUSTOMER["legal_name"],
                    "contact_name": contact["name"],
                    "contact_email": contact["email"],
                    "contact_phone": contact["phone"],
                    "vat_id": CUSTOMER["vat_id"],
                    "iban": CUSTOMER["iban"],
                    "street": CUSTOMER["street"],
                    "postcode_city": CUSTOMER["postcode_city"],
                    "description": desc,
                    "quantity": german_qty(qty),
                    "unit_price": german(price, places=3 if price.as_tuple().exponent < -2 else 2),
                    "vat_rate": str(rate),
                }
            )
        ref = reference_totals(lines)
        totals_rows.append({"invoice_no": number, "gross": german(ref["gross"])})
        all_invoices.append({"number": number, "lines": lines, "totals": ref, "big": i in big_slots})

    with open(out / "invoices.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    with open(out / "customer_totals.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["invoice_no", "gross"], delimiter=";")
        writer.writeheader()
        writer.writerows(totals_rows)
    (out / "customer.json").write_text(json.dumps(CUSTOMER, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"invoices": all_invoices}


def write_complaint(out: Path, mismatches: list[tuple[str, str, str]]) -> None:
    """The customer's email, as support received it. Lists the cent differences they noticed."""
    contact = CUSTOMER["contacts"][0]
    listed = "\n".join(f"  - {number}: Ledgerly {ours} EUR, our books {theirs} EUR" for number, ours, theirs in mismatches)
    text = f"""From: {contact['name']} <{contact['email']}>
To: support@ledgerly.example
Subject: Rechnungsbeträge stimmen nicht / invoice totals don't match

Hello Ledgerly team,

during our month-end reconciliation several of your invoice totals are off by a cent compared to our
accounting system. Examples:
{listed}

Our auditor needs this resolved before the quarterly VAT return. Please call me on {contact['phone']} if
you need anything. Our VAT ID is {CUSTOMER['vat_id']}.

Best regards
{contact['name']}
{CUSTOMER['legal_name']}, {CUSTOMER['street']}, {CUSTOMER['postcode_city']}
"""
    (out / "complaint.txt").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(Path(__file__).parent / "eu-vault"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    out = Path(args.out)
    data = generate(out, args.seed)

    # Which invoices does today's (buggy) float arithmetic get wrong by a cent? The customer noticed three.
    def float_gross(lines):
        net = sum(round(float(q) * float(p), 2) for _d, q, p, _r in lines)
        vat = sum(round(round(float(q) * float(p), 2) * r / 100, 2) for _d, q, p, r in lines)
        return round(net + vat, 2)

    cent_off = []
    for inv in data["invoices"]:
        ours = Decimal(str(float_gross(inv["lines"]))).quantize(CENT)
        if ours != inv["totals"]["gross"] and not inv["big"]:
            cent_off.append((inv["number"], german(ours), german(inv["totals"]["gross"])))
    write_complaint(out, cent_off[:3])
    print(f"wrote {out}: {len(data['invoices'])} invoices, {len(cent_off)} with cent differences, "
          f"{sum(i['big'] for i in data['invoices'])} with amounts >= 1.000")


if __name__ == "__main__":
    main()
