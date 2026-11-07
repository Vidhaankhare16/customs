# Ledgerly invoicing rules

Ledgerly is the small invoicing library the Customs demo team maintains. These are the rules its totals must
follow. Customers reconcile Ledgerly's totals against their own accounting, so a one-cent difference is a bug.

1. **Money is exact.** Amounts are decimal, never binary floating point.
2. **Line net** = `quantity × unit_price`, rounded to cents **half away from zero** ("kaufmännische
   Rundung": 0.005 → 0.01, −0.005 → −0.01).
3. **Line VAT** = `line_net × vat_rate`, rounded to cents half away from zero.
4. **Invoice totals:** `net` = sum of line nets, `vat` = sum of line VAT, `gross` = `net + vat`.
5. **Credit notes** are ordinary invoices with negative quantities. Rule 2's rounding applies symmetrically.
6. **Imports.** The CSV importer accepts amounts written the way the customer's locale writes them. German
   customers export `1.234,56` (dot for thousands, comma for decimals). An amount Ledgerly cannot parse is an
   **error**, never a silently dropped line.
