"""2.0.0 (#156): built-in check style presets. An Administrator creates a check style from a preset and fine-tunes it.

"3 per page - standard laser (top check first)" was measured from the product owner's stock (Classic Tan laser 3-up,
stock code STKDK06, order code LA104-1) and his Word templates, and checked against a scan of the stock:
- Letter sheet, three checks of 3.5" (perforation to perforation, including the bank-number strip), 0.5" footer.
- He prints the top check and tears it off; the 2-check piece prints the same way; the last check (footer strip torn
  off) is fed through the manual feed like an envelope, date end first.

Field boxes are the area the text occupies: the text sits on the bottom of its box (baseline = box bottom minus the
font's descent), so a box placed on a pre-printed line puts the writing on the line. The positions reproduce his
Word templates (Word text boxes plus their internal margins).
"""
from __future__ import annotations

import copy

STANDARD_3UP = {
    "stock": {
        "paper_width": 8.5, "paper_height": 11.0, "check_width": 8.5, "check_height": 3.5,
        "check_tops": [0.0, 3.5, 7.0], "sheet_usage": "TEAR_TOP", "signature_lines": 1,
        "stock_note": "Measured from Classic Tan laser 3-up stock (STKDK06 / LA104-1).",
        "outline": [
            {"kind": "BOX", "x": 0.05, "y": 0.02, "x2": 8.47, "y2": 3.04},
            {"kind": "TEXT", "x": 7.3, "y": 0.25, "text": "(check no. pre-printed)", "size": 6},
            {"kind": "LINE", "x": 6.95, "y": 0.99, "x2": 8.2, "y2": 0.99},
            {"kind": "TEXT", "x": 0.27, "y": 1.33, "text": "PAY TO THE", "size": 8},
            {"kind": "TEXT", "x": 0.27, "y": 1.45, "text": "ORDER OF", "size": 8},
            {"kind": "LINE", "x": 0.82, "y": 1.47, "x2": 6.7, "y2": 1.47},
            {"kind": "TEXT", "x": 6.8, "y": 1.47, "text": "$", "size": 14},
            {"kind": "LINE", "x": 0.27, "y": 1.81, "x2": 7.75, "y2": 1.81},
            {"kind": "TEXT", "x": 7.77, "y": 1.8, "text": "DOLLARS", "size": 8},
            {"kind": "TEXT", "x": 0.27, "y": 2.75, "text": "MEMO", "size": 8},
            {"kind": "LINE", "x": 4.86, "y": 2.69, "x2": 8.2, "y2": 2.69},
            {"kind": "TEXT", "x": 6.05, "y": 2.79, "text": "AUTHORIZED SIGNATURE", "size": 6},
            {"kind": "TEXT", "x": 1.6, "y": 3.28, "text": "(bank numbers pre-printed)", "size": 7},
        ],
    },
    "defaults": {"font": "SANS", "size": 10, "upper": True},
    "fields": {
        "date": {"x": 7.0, "y": 0.73, "w": 1.15, "h": 0.25, "align": "LEFT"},
        "payee": {"x": 1.275, "y": 1.206, "w": 5.35, "h": 0.25, "align": "LEFT"},
        "amount_number": {"x": 6.98, "y": 1.245, "w": 1.27, "h": 0.25, "font": "MONO", "align": "RIGHT"},
        "amount_words": {"x": 0.72, "y": 1.506, "w": 6.93, "h": 0.25, "align": "LEFT"},
        "memo": {"x": 0.75, "y": 2.51, "w": 3.81, "h": 0.25, "font": "SERIF", "align": "LEFT"},
        "signature": {"x": 5.605, "y": 2.15, "w": 2.25, "h": 0.7},
    },
    "amount_words": {"and_mode": "CENTS", "hyphens": True, "case": "UPPER", "cents": "NN", "fill": "DOTS",
                     "fill_placement": "BETWEEN", "trailing_word": ""},
    "amount_number": {"commas": True, "dollar_sign": False, "lead_fill": "**"},
    "date_format": "MM/DD/YYYY",
    "memo_default": "{BUDGET_CODE}, INVOICE {INVOICE}",
    "signature_limit_cents": None,
    "default_signer_id": None,
    "feed_modes": [
        {"key": "sheet_top", "label": "Sheet - top check", "kind": "SHEET", "position": 0,
         "note": "Full sheet, or the 2-check piece after the top check was torn off."},
        {"key": "last_check", "label": "Last check - envelope feed, date end first", "kind": "SINGLE",
         "lead": "DATE_END", "page": "LETTER", "guide": "CENTER",
         "note": "Tear off the 1/2 inch footer strip, then feed the check through the manual feed like an envelope, "
                 "date end first."},
    ],
}

# 2.0.0 (#167): voucher check, check on top - one 3.5" check per Letter sheet, then two detail stubs, perforated at
# 3.5" and 7" (the common layout of laser voucher checks from the major check suppliers). The check face uses the
# same field positions as the 3-up preset; the Administrator fine-tunes them with the calibration page.
VOUCHER_TOP = copy.deepcopy(STANDARD_3UP)
VOUCHER_TOP["stock"].update({
    "check_tops": [0.0], "sheet_usage": "TEAR_TOP",
    "stock_note": "Voucher check, check on top: check 0-3.5 in, stubs 3.5-7 in and 7-11 in (published layout).",
})
VOUCHER_TOP["feed_modes"] = [
    {"key": "voucher", "label": "Voucher sheet", "kind": "SHEET", "position": 0,
     "note": "One voucher sheet per check, check at the top."},
]
VOUCHER_TOP["stubs"] = [
    {"top": 3.5, "height": 3.5, "copy_kind": "VENDOR", "title": "{ORG}", "show_check_number": True},
    {"top": 7.0, "height": 4.0, "copy_kind": "OFFICE", "title": "{ORG}", "show_check_number": True},
]

# Two signature lines (any style can switch them on; the voucher preset keeps one): the second line sits above the
# first, the same width.
SIGNATURE2_DEFAULT = {"x": 5.605, "y": 1.95, "w": 2.25, "h": 0.42}

PRESETS = {
    "STANDARD_3UP": {
        "name": "3 per page - standard laser (top check first)",
        "description": "Letter sheet with three 3.5-inch checks. Print the top check and tear it off; the last check "
                       "is fed through the manual feed like an envelope.",
        "config": STANDARD_3UP,
    },
    "VOUCHER_TOP": {
        "name": "Voucher - check on top, two stubs",
        "description": "Letter sheet with one 3.5-inch check at the top and two detail stubs below (vendor copy and "
                       "office copy) listing the invoices paid.",
        "config": VOUCHER_TOP,
    },
}


def options() -> list[dict]:
    return [{"key": k, "name": v["name"], "description": v["description"]} for k, v in PRESETS.items()]


def config_for(key: str) -> dict:
    return copy.deepcopy(PRESETS[key]["config"])
