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
}
MULTILINE = (LETTER, ENVELOPE)     # contexts whose text may contain line breaks
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class PatternError(ValueError):
    def __init__(self, message: str, variable: str | None = None, suggestion: str | None = None):
        super().__init__(message)
        self.variable, self.suggestion = variable, suggestion


@dataclass
class Token:
    literal: str | None = None
    var: str | None = None


def variable_options(context: str = CHECK) -> list[dict]:
    return [{"name": k, "description": d} for k, (d, ctxs) in VARIABLES.items() if context in ctxs]


def _suggest(name: str, context: str) -> str | None:
    names = [k for k, (_d, ctxs) in VARIABLES.items() if context in ctxs]
    m = difflib.get_close_matches(name.upper(), names, n=1, cutoff=0.5)
    return m[0] if m else None


def parse(pattern: str, context: str = CHECK) -> list[Token]:
    if pattern is None:
        return []
    limit = MAX_TEXT if context in (LETTER,) else MAX_PATTERN
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
