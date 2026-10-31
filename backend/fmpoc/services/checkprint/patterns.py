"""2.0.0 (#160): field patterns - literal text plus {VARIABLES} filled from the transaction.

- Anything outside braces prints exactly as typed. `{{` prints "{" and `}}` prints "}".
- `{NAME}` is a variable; names ignore case. A name that does not exist is an error (printing is blocked) with the
  closest match suggested - it is never printed as literal text.
- A known variable with no data (e.g. {INVOICE} on a line without an invoice number) is a warning the user accepts
  or fixes before printing.
- Split transactions: line-level variables give the first value plus " and others".

Substitution is a fixed table lookup: patterns are never evaluated or passed to anything else (BR-102).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

AND_OTHERS = " and others"
MAX_PATTERN = 200
MAX_TEXT = 2000        # letter paragraphs

# name -> (description, contexts it may be used in)
CHECK, LETTER, ENVELOPE, STUB = "CHECK", "LETTER", "ENVELOPE", "STUB"
RECEIPT = "RECEIPT"        # 2.1.0 (#312): donation receipt letters (not in ALL: the check variables don't apply)
ALL = (CHECK, LETTER, ENVELOPE, STUB)
VARIABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "PAYEE": ("Payee name", ALL),
    "DATE": ("Transaction date", ALL),
    "AMOUNT": ("Transaction total, e.g. 3,199.30", ALL),
    "BUDGET": ("Budget name (first one + \"and others\" when split)", ALL),
    "BUDGET_CODE": ("Budget code, e.g. 51 or 51-02 (first one + \"and others\" when split)", ALL),
    "INVOICE": ("Invoice number (first one + \"and others\" when split)", ALL),
    "DESCRIPTION": ("Line description (first one + \"and others\" when split)", ALL),
    "NOTES": ("Transaction notes", ALL),
    "CHECK_NUMBER": ("Check number from the register (letters, envelopes and stubs - never the check itself)",
                     (LETTER, ENVELOPE, STUB)),
    "ORG": ("Organization name", ALL),
    "ACCOUNT": ("Bank account name (never the account number)", ALL),
    # 2.0.0 (#165, #166): letters, envelopes and stubs
    "INVOICE_DATE": ("Invoice date (first one + \"and others\" when split)", (LETTER, ENVELOPE, STUB)),
    "TODAY": ("Today's date (the day it is printed)", (LETTER, ENVELOPE, STUB)),
    "PAYEE_ADDRESS": ("Payee's address from the entity (several lines)", (LETTER, ENVELOPE)),
    "SIGNER": ("Name of the check's signer", (LETTER,)),
    "SIGNER_TITLE": ("Title of the check's signer", (LETTER,)),
    # 2.1.0 (#312): donation receipts
    "DONOR_NAME": ("Donor's name (the entity on the donation lines)", (RECEIPT,)),
    "DONOR_ADDRESS": ("Donor's address from the entity (several lines)", (RECEIPT,)),
    "DATE_RECEIVED": ("Date the donation was received (the deposit's date)", (RECEIPT,)),
    "PURPOSE": ("Purpose of the donation (as marked on the deposit)", (RECEIPT,)),
    "ORG_NAME": ("Organization name (same as {ORG.NAME})", (RECEIPT,)),
    "ORG_ADDRESS": ("Organization's address, several lines (same as {ORG.ADDRESS})", (RECEIPT,)),
    "ORG_EIN": ("Organization's EIN (same as {ORG.EIN})", (RECEIPT,)),
    "RECEIPT_NO": ("Receipt number, e.g. R-2026-0001", (RECEIPT,)),
    "DETAILS": ("Details written for this donation in the Donation receipt dialog (a paragraph of its own is left "
                "out when there are none)", (RECEIPT,)),
}
# 2.1.0 (#314): the organization profile, everywhere (the address, several lines, where line breaks are allowed)
EVERYWHERE = ALL + (RECEIPT,)
for _k, _d in (("NAME", "Organization name"), ("ADDRESS1", "Organization's street address"),
               ("ADDRESS2", "Organization's address, second line"), ("CITY", "Organization's city"),
               ("STATE", "Organization's state"), ("ZIP", "Organization's ZIP code"),
               ("COUNTRY", "Organization's country"), ("PHONE", "Organization's phone"),
               ("EMAIL", "Organization's email"), ("EIN", "Organization's EIN")):
    VARIABLES[f"ORG.{_k}"] = (_d + " (System/About → Organization)", EVERYWHERE)
VARIABLES["ORG.ADDRESS"] = ("Organization's address, several lines (System/About → Organization)",
                            (LETTER, ENVELOPE, RECEIPT))
VARIABLES["ORG"] = (VARIABLES["ORG"][0], VARIABLES["ORG"][1] + (RECEIPT,))
for _k in ("TODAY", "AMOUNT", "SIGNER", "SIGNER_TITLE"):        # shared with the receipt, described for it below
    VARIABLES[_k] = (VARIABLES[_k][0], VARIABLES[_k][1] + (RECEIPT,))
RECEIPT_DESCRIPTIONS = {"AMOUNT": "Amount of this donor's donation, e.g. 100.00",
                        "SIGNER": "Name of the person signing the receipt",
                        "SIGNER_TITLE": "Title of the person signing the receipt"}
# 2.2.0 (#256): the year-end giving statement - the receipt's donor and organization variables plus the year's
STATEMENT = "STATEMENT"
for _k in ("DONOR_NAME", "DONOR_ADDRESS", "ORG_NAME", "ORG_ADDRESS", "ORG_EIN", "ORG", "TODAY", "SIGNER", "SIGNER_TITLE",
           "ORG.ADDRESS") + tuple(k for k in VARIABLES if k.startswith("ORG.")):
    if STATEMENT not in VARIABLES[_k][1]:
        VARIABLES[_k] = (VARIABLES[_k][0], VARIABLES[_k][1] + (STATEMENT,))
VARIABLES["YEAR"] = ("Calendar year of the statement, e.g. 2026", (STATEMENT,))
VARIABLES["TOTAL"] = ("Total money given in the year, e.g. 1,250.00 (items have no value)", (STATEMENT,))
VARIABLES["STATEMENT_NO"] = ("Statement number, e.g. S-2026-0001", (STATEMENT,))
VARIABLES["DONATION_TABLE"] = ("The table of the year's donations (a paragraph of its own; printed after the text "
                               "when the letter doesn't have it)", (STATEMENT,))
# 2.2.0 (#317): dotted entity variables by role ({ORG.*} is above); several-line fields only where line breaks are allowed
from ..entity_vars import FIELDS as _EF, MULTILINE_FIELDS as _EM   # noqa: E402
for _k, _d in _EF.items():
    VARIABLES[f"PAYEE.{_k}"] = (f"Payee's {_d}", (LETTER, ENVELOPE) if _k in _EM else ALL)
    VARIABLES[f"DONOR.{_k}"] = (f"Donor's {_d}", (RECEIPT, STATEMENT))
# 2.4.0 (#253 part 3): the invoice PDF template - organization, customer and invoice variables
INVOICE_DOC = "INVOICE"
for _k in ("ORG", "TODAY", "ORG.ADDRESS") + tuple(k for k in VARIABLES if k.startswith("ORG.")):
    if INVOICE_DOC not in VARIABLES[_k][1]:
        VARIABLES[_k] = (VARIABLES[_k][0], VARIABLES[_k][1] + (INVOICE_DOC,))
for _k, _d in _EF.items():
    VARIABLES[f"CUSTOMER.{_k}"] = (f"Customer's {_d}", (INVOICE_DOC,))
for _k, _d in (("NUMBER", "Invoice number, e.g. INV-2027-0042 (with -R1 when revised)"), ("DATE", "Invoice date"),
               ("DUE_DATE", "Due date"), ("TOTAL", "Invoice total, e.g. 1,250.00"),
               ("BALANCE", "Amount still due, e.g. 250.00"), ("TERMS", "Payment terms, e.g. Net 30")):
    VARIABLES[f"INVOICE.{_k}"] = (_d, (INVOICE_DOC,))
MULTILINE = (LETTER, ENVELOPE, RECEIPT, STATEMENT, INVOICE_DOC)     # contexts whose text may contain line breaks
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?")    # 2.1.0 (#314): ORG.NAME


class PatternError(ValueError):
    def __init__(self, message: str, variable: str | None = None, suggestion: str | None = None):
        super().__init__(message)
        self.variable, self.suggestion = variable, suggestion


@dataclass
class Token:
    literal: str | None = None
    var: str | None = None


def variable_options(context: str = CHECK) -> list[dict]:
    return [{"name": k, "description": RECEIPT_DESCRIPTIONS.get(k, d) if context in (RECEIPT, STATEMENT) else d}
            for k, (d, ctxs) in VARIABLES.items() if context in ctxs]


def _suggest(name: str, context: str) -> str | None:
    names = [k for k, (_d, ctxs) in VARIABLES.items() if context in ctxs]
    m = difflib.get_close_matches(name.upper(), names, n=1, cutoff=0.5)
    return m[0] if m else None


def parse(pattern: str, context: str = CHECK) -> list[Token]:
    if pattern is None:
        return []
    limit = MAX_TEXT if context in (LETTER, RECEIPT, STATEMENT, INVOICE_DOC) else MAX_PATTERN
    if len(pattern) > limit:
        raise PatternError(f"The text is longer than {limit} characters.")
    allowed = {"\n"} if context in MULTILINE else set()
    if any(ord(ch) < 32 and ch not in allowed for ch in pattern):
        raise PatternError("The text may not contain line breaks or control characters." if not allowed
                           else "The text may not contain control characters.")
    out: list[Token] = []
    buf: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "{":
            if pattern.startswith("{{", i):
                buf.append("{")
                i += 2
                continue
            end = pattern.find("}", i + 1)
            if end < 0:
                raise PatternError("A \"{\" is not closed. Use {{ to print a brace.")
            name = pattern[i + 1:end].strip()
            if not _NAME.fullmatch(name):
                raise PatternError(f"\"{{{pattern[i + 1:end]}}}\" is not a variable name. Use {{{{ and }}}} to print "
                                   f"braces.", variable=pattern[i + 1:end])
            key = name.upper()
            if key not in VARIABLES:
                sug = _suggest(key, context)
                raise PatternError(f"{{{name}}} is not a variable." + (f" Did you mean {{{sug}}}?" if sug else ""),
                                   variable=name, suggestion=sug)
            if context not in VARIABLES[key][1]:
                raise PatternError(f"{{{key}}} cannot be used here.", variable=name)
            if buf:
                out.append(Token(literal="".join(buf)))
                buf = []
            out.append(Token(var=key))
            i = end + 1
        elif ch == "}":
            if pattern.startswith("}}", i):
                buf.append("}")
                i += 2
                continue
            raise PatternError("A \"}\" has no matching \"{\". Use }} to print a brace.")
        else:
            buf.append(ch)
            i += 1
    if buf:
        out.append(Token(literal="".join(buf)))
    return out


@dataclass
class Resolved:
    text: str
    empty: list[str] = field(default_factory=list)       # variables that had no data


def resolve(pattern: str, values: dict[str, str], context: str = CHECK) -> Resolved:
    tokens = parse(pattern, context)
    parts, empty = [], []
    for t in tokens:
        if t.literal is not None:
            parts.append(t.literal)
        else:
            v = (values.get(t.var) or "").strip()
            if not v and t.var not in empty:
                empty.append(t.var)
            parts.append(v)
    return Resolved("".join(parts), empty)


def first_and_others(values: list[str | None]) -> str:
    seen: list[str] = []
    for v in values:
        v = (v or "").strip()
        if v and v not in seen:
            seen.append(v)
    if not seen:
        return ""
    return seen[0] + (AND_OTHERS if len(seen) > 1 else "")
