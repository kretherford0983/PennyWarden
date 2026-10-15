"""2.0.0 (#157): the amount in words and the number amount. Both are generated from the same whole-cent total
(BR-046); neither is ever typed. Default style is bank convention in capitals:
"THREE THOUSAND ONE HUNDRED NINETY-NINE AND" + fill + "30/100"."""
from __future__ import annotations

from dataclasses import dataclass

MAX_CENTS = 99_999_999_999  # 999,999,999.99

_ONES = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE",
         "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
_TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]
_SCALES = [(1_000_000, "MILLION"), (1_000, "THOUSAND")]


def _below_100(n: int, hyphens: bool) -> str:
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    if not o:
        return _TENS[t]
    return f"{_TENS[t]}{'-' if hyphens else ' '}{_ONES[o]}"


def _below_1000(n: int, hyphens: bool, and_in_hundreds: bool) -> str:
    h, rest = divmod(n, 100)
    parts = []
    if h:
        parts.append(f"{_ONES[h]} HUNDRED")
        if rest and and_in_hundreds:
            parts.append("AND")
    if rest or not h:
        parts.append(_below_100(rest, hyphens))
    return " ".join(parts)


def dollars_in_words(dollars: int, *, hyphens: bool = True, and_in_hundreds: bool = False) -> str:
    if dollars < 0:
        raise ValueError("negative amount")
    if dollars == 0:
        return "ZERO"
    parts = []
    rest = dollars
    for value, name in _SCALES:
        if rest >= value:
            q, rest = divmod(rest, value)
            parts.append(f"{_below_1000(q, hyphens, and_in_hundreds)} {name}")
    if rest:
        parts.append(_below_1000(rest, hyphens, and_in_hundreds))
    return " ".join(parts)


@dataclass(frozen=True)
class WordsParts:
    words: str        # "THREE THOUSAND ONE HUNDRED NINETY-NINE AND"
    cents: str        # "30/100"
    trailing: str     # "" or e.g. "DOLLARS"


def words_parts(cents: int, style: dict) -> WordsParts:
    """`style` is the check style's amount_words settings (config.AmountWords as a dict)."""
    if cents <= 0 or cents > MAX_CENTS:
        raise ValueError("amount out of range")
    dollars, c = divmod(cents, 100)
    words = dollars_in_words(dollars, hyphens=style.get("hyphens", True),
                             and_in_hundreds=style.get("and_mode") == "HUNDREDS")
    words = f"{words} AND"
    cents_txt = "NO/100" if (c == 0 and style.get("cents") == "NO") else f"{c:02d}/100"
    case = style.get("case", "UPPER")
    trailing = (style.get("trailing_word") or "").strip()

    def cased(s: str) -> str:
        if case == "TITLE":  # "One Hundred Ninety-Nine and"
            words_ = ["and" if w == "AND" else "-".join(p.capitalize() for p in w.split("-")) for w in s.split(" ")]
            return " ".join(words_)
        if case == "LOWER":
            return s.lower()
        return s.upper()

    return WordsParts(cased(words), cents_txt, cased(trailing) if trailing else "")


def number_text(cents: int, style: dict) -> str:
    """`style` is the amount_number settings: commas, dollar sign, leading fill."""
    if cents <= 0 or cents > MAX_CENTS:
        raise ValueError("amount out of range")
    dollars, c = divmod(cents, 100)
    body = f"{dollars:,}" if style.get("commas", True) else str(dollars)
    body = f"{body}.{c:02d}"
    if style.get("dollar_sign"):
        body = "$" + body
    return (style.get("lead_fill") or "") + body
