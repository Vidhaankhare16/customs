from ledgerly.importer import import_csv
from ledgerly.invoice import totals

HEADER = "invoice_no;customer_id;description;quantity;unit_price;vat_rate\n"


def test_import_german_decimal_comma(tmp_path):
    path = tmp_path / "export.csv"
    path.write_text(HEADER + "INV-1;TEST;Widget;2;12,50;19\n", encoding="utf-8")
    [invoice] = import_csv(path)
    assert totals(invoice)["gross"] == 29.75


def test_import_groups_lines_by_invoice(tmp_path):
    path = tmp_path / "export.csv"
    path.write_text(
        HEADER + "INV-1;TEST;A;1;10,00;19\nINV-1;TEST;B;1;5,00;7\nINV-2;TEST;C;3;1,00;19\n",
        encoding="utf-8",
    )
    invoices = {inv.number: inv for inv in import_csv(path)}
    assert len(invoices["INV-1"].lines) == 2
    assert len(invoices["INV-2"].lines) == 1
