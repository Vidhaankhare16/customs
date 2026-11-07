from ledgerly.invoice import Invoice, Line, totals


def test_single_line_invoice():
    invoice = Invoice("T-1", "TEST", [Line("Widget", 2, 10.00, 0.19)])
    assert totals(invoice) == {"net": 20.00, "vat": 3.80, "gross": 23.80}


def test_two_rates():
    invoice = Invoice(
        "T-2",
        "TEST",
        [Line("Food", 1, 100.00, 0.07), Line("Drinks", 1, 50.00, 0.19)],
    )
    assert totals(invoice) == {"net": 150.00, "vat": 16.50, "gross": 166.50}


def test_empty_invoice():
    assert totals(Invoice("T-3", "TEST")) == {"net": 0, "vat": 0, "gross": 0}
