"""2.3.0 polish (Kyle, 2026-10-31): a letter's signature must not end up alone on page 2. Donation receipts,
year-end statements and payment cover letters: (1) a letter that just overflows is fitted to one page (tighter
spacing, then up to 1 pt smaller type); (2) when two pages are needed, the last paragraph goes to page 2 with the
closing and signature; (3) page 2 onward carries "<organization> · <document> · Page N of M", page 1 "Continued on
page 2"."""
from __future__ import annotations

import datetime as dt
import io

import pytest
from pypdf import PdfReader

from fmpoc.services import donation_statements as stm
from fmpoc.services import donations as dn
from fmpoc.services import letter_fit, signers
from fmpoc.services.checkprint import documents

ORG = {"ORG.NAME": "Sample Club", "ORG.ADDRESS": "1 Main St\nSample Town, US 55555", "ORG.EIN": "00-0000000",
       "ORG": "Sample Club", "ORG_NAME": "Sample Club", "ORG_ADDRESS": "1 Main St", "ORG_EIN": "00-0000000"}
SIGNER = "Jordan Signer"
NOTE = "Donated items are listed by description only"


def _pages(pdf: bytes) -> list[str]:
    return [p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages]


def _receipt(n_items: int, mode: str = "PRINTED") -> bytes:
    cfg = dn.ReceiptConfig()
    data = dn.ReceiptData(number="R-2026-0004", kind=dn.ORIGINAL, kind_note="", org=ORG, donor_name="Pat Donor",
                          donor_address=["2 Oak Ave", "Sample Town, US 55555"], amount_cents=25000,
                          dates=[dt.date(2026, 8, 3)], purposes=["General support"],
                          items=[f"Item number {i} - a donated thing for the auction" for i in range(n_items)],
                          details="How the gift will be used, written by the Register User.",
                          signature=signers.SignatureBlock(mode=mode, name=SIGNER, title="Treasurer"))
    return dn.receipt_pdf(cfg, data)


def _unfitted(monkeypatch, fn, *a):
    monkeypatch.setattr(letter_fit, "TRIES", ((1.0, 0.0),))
    try:
        return fn(*a)
    finally:
        monkeypatch.undo()


def _boundary(monkeypatch, make, limit=80) -> int:
    """The smallest size at which the normal layout needs two pages."""
    for n in range(1, limit):
        if len(_pages(_unfitted(monkeypatch, make, n))) == 2:
            return n
    pytest.fail("no two-page layout found")


def test_receipt_that_just_overflows_is_fitted_to_one_page(monkeypatch):
    n = _boundary(monkeypatch, _receipt)
    pages = _pages(_receipt(n))
    assert len(pages) == 1 and SIGNER in pages[0] and "Page 1 of" not in pages[0]


def test_receipt_on_two_pages_never_leaves_the_signature_alone(monkeypatch):
    n = _boundary(monkeypatch, _receipt)
    for k in range(n, n + 40):                     # past what fitting can absorb
        pages = _pages(_receipt(k))
        if len(pages) == 2:
            break
    else:
        pytest.fail("never needed two pages")
    first, second = pages
    assert SIGNER in second and NOTE in second.replace("\n", " ")       # the last paragraph went with it
    assert "Sample Club · Donation receipt R-2026-0004 · Page 2 of 2" in second
    assert "Continued on page 2" in first and "Page" not in first.replace("Continued on page 2", "")


def test_room_to_sign_by_hand_is_not_squeezed():
    a = letter_fit.scale_spacers([letter_fit.FixedSpacer(1, 30), letter_fit.Spacer(1, 30)], 0.5)
    assert a[0].height == 30 and a[1].height == 15


def _statement(n_rows: int) -> bytes:
    cfg = dn.ReceiptConfig()
    rows = [{"line_id": i, "date": dt.date(2026, 8, 3), "receipt": f"R-2026-{i:04d}", "description": f"Gift {i}",
             "amount_cents": 1000, "kind": "MONEY", "goods_cents": 0, "goods_description": ""} for i in range(n_rows)]
    return stm.statement_pdf(cfg, org=ORG, donor_name="Pat Donor", donor_address=["2 Oak Ave"], year=2026,
                             number="S-2026-0001", kind=dn.ORIGINAL, kind_note="", rows=rows,
                             total_cents=1000 * n_rows, goods=[], items=[], today=dt.date(2027, 1, 5),
                             signature=signers.SignatureBlock(mode="PRINTED", name=SIGNER, title="Treasurer"))


def test_statement_fits_or_carries_its_last_paragraph(monkeypatch):
    n = _boundary(monkeypatch, _statement)
    assert len(_pages(_statement(n))) == 1
    pages = _pages(_statement(n + 25))
    assert len(pages) >= 2
    assert SIGNER in pages[-1] and "No goods or services" in pages[-1]
    assert f"Year-end giving statement S-2026-0001 · Page {len(pages)} of {len(pages)}" in pages[-1]


def _letter(n_rows: int, mode: str = "PRINTED") -> bytes:
    cfg = documents.LetterConfig()
    rows = [{"INVOICE": str(1000 + i), "INVOICE_DATE": "08/29/2026", "DESCRIPTION": "Supplies", "BUDGET": "1000",
             "NOTES": "", "AMOUNT": "$10.00"} for i in range(n_rows)]
    data = documents.LetterData(values={"ORG": "Sample Club", "CHECK_NUMBER": "1042", "TODAY": "08/30/2026"},
                                rows=rows, total=f"${10 * n_rows}.00", payee_lines=["Vendor Co", "3 Elm St"],
                                signer_name=SIGNER, signer_title="Treasurer", signature_mode=mode)
    return documents.letter_pdf(cfg, data)


def test_cover_letter_fits_or_keeps_the_closing_with_the_signature(monkeypatch):
    n = _boundary(monkeypatch, _letter)
    assert len(_pages(_letter(n))) == 1
    pages = _pages(_letter(n + 30))
    assert len(pages) >= 2
    last = pages[-1].replace("\n", " ")
    assert SIGNER in last and "Thank you for your continued service" in last and "Sincerely" in last
    assert f"Sample Club · Cover letter · Check 1042 · Page {len(pages)} of {len(pages)}" in last
    assert "Continued on page 2" in pages[0]


def test_short_letters_are_unchanged():
    for pdf in (_receipt(1), _statement(2), _letter(2)):
        pages = _pages(pdf)
        assert len(pages) == 1 and "Continued" not in pages[0] and "Page 1" not in pages[0]
