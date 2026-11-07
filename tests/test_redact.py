from conftest import VAULT

from customs.redact import Border, Pseudonyms
from customs.services import VaultCaseFiles


def border():
    return Border(VaultCaseFiles(VAULT).registries(), Pseudonyms())


def categories(findings):
    return {f.category for f in findings}


def test_finds_registry_personal_data_in_any_spacing():
    b = border()
    assert "email" in categories(b.find_personal("mail jana.wolff@brauhaus-lindenhof.de"))
    assert "iban" in categories(b.find_personal("IBAN DE44500105175407324931"))  # spaces removed
    assert "phone" in categories(b.find_personal("call +49 30 5557 0142"))
    assert "person_name" in categories(b.find_personal("as Wolff said on the phone"))
    assert "address" in categories(b.find_personal("ship to Lindenstraße 17"))


def test_finds_unknown_personal_data_by_pattern():
    b = border()
    assert "email" in categories(b.find_personal("cc someone@else.example"))
    assert "iban" in categories(b.find_personal("FR76 3000 6000 0112 3456 7890 189"))
    assert "vat_id" in categories(b.find_personal("VAT FR12345678901"))


def test_business_content_is_not_personal_data():
    b = border()
    text = ("[INV-2] still off by -0,01; 2 x rows_dropped_on_import; unit_price=d.ddd,dd; "
            "pytest: 12 passed; commit 3f9c2ab; Reconciled 38/40 invoices")
    assert b.find_personal(text) == []


def test_findings_name_the_location_never_the_value():
    findings = border().find_personal("jana.wolff@brauhaus-lindenhof.de", "next[0]")
    assert {f.category for f in findings} == {"email", "person_name"}
    assert all(f.location == "next[0]" for f in findings)
    assert "jana" not in repr(findings).lower()


def test_identifiers_are_pseudonymised_and_reidentified_consistently():
    b = border()
    out = b.pseudonymise("BL-2026-0105 and BL-2026-0101 for Brauhaus Lindenhof GmbH, again BL-2026-0105")
    assert out == "[INV-1] and [INV-2] for [CUSTOMER-1], again [INV-1]"
    assert b.reidentify("please re-check [INV-2] and [INV-9]") == "please re-check BL-2026-0101 and [INV-9]"


def test_scrub_removes_everything_personal():
    b = border()
    complaint = (VAULT / "complaint.txt").read_text(encoding="utf-8")
    scrubbed = b.scrub(complaint)
    assert b.find_personal(scrubbed) == []
    assert "BL-2026" not in scrubbed
    assert "312,59" in scrubbed  # business amounts survive
