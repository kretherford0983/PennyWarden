"""2.0.0 (#156): the check style settings document. A check style has three parts:

1. stock     - the paper, where each check sits on the sheet, how the sheet is used, the outline of what is pre-printed
               (for the setup preview only, never printed);
2. fields    - where each field prints, measured once from the check's top-left corner in inches, with its font;
3. feed modes - how the paper goes into the printer, chosen at print time, each with its own small offset.

Everything is validated here, server-side (BR-094/BR-097). Positions are inches from the check's top-left corner
(x to the right, y down). Nothing may be placed in the bottom 5/8" of the check (the bank-number clear zone).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import fonts

CLEAR_ZONE = 0.625            # bottom 5/8" of a check: the MICR (bank-number) clear band
FEED_OFFSET_MAX = 0.5         # an Administrator's per-feed-mode offset, inches
PERSONAL_MAX = 0.25           # a user's personal adjustment, inches
LETTER = (8.5, 11.0)
TEXT_FIELDS = ("date", "payee", "amount_number", "amount_words", "memo")
FIELD_LABELS = {"date": "Date", "payee": "Pay to", "amount_number": "Amount (number)",
                "amount_words": "Amount (words)", "memo": "Memo", "signature": "Signature",
                "signature2": "Second signature"}
STUB_COLUMN_KEYS = ("INVOICE", "INVOICE_DATE", "DESCRIPTION", "BUDGET", "NOTES", "AMOUNT")
MAX_STUBS = 2
STUB_MIN_HEIGHT = 1.5
DATE_FORMATS = {"MM/DD/YYYY": "%m/%d/%Y", "MM/DD/YY": "%m/%d/%y", "YYYY-MM-DD": "%Y-%m-%d",
                "MONTH D, YYYY": "MONTH"}

Inch = Field(ge=0, le=11)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")   # BR-098: unknown settings are refused, never stored


def _r(v: float) -> float:
    return round(float(v), 3)


class OutlineItem(_M):
    """Something pre-printed on the stock (a line, a label, a box), drawn in the setup preview only."""
    kind: Literal["LINE", "TEXT", "BOX"]
    x: float = Inch
    y: float = Inch
    x2: float | None = Field(default=None, ge=0, le=11)
    y2: float | None = Field(default=None, ge=0, le=11)
    text: str | None = Field(default=None, max_length=40)
    size: float | None = Field(default=None, ge=4, le=24)


class Stock(_M):
    paper_width: float = 8.5
    paper_height: float = 11.0
    check_width: float = Field(ge=2, le=8.5)
    check_height: float = Field(ge=1, le=11)
    check_tops: list[float] = Field(min_length=1, max_length=3)    # top of each check on the sheet, from the top edge
    sheet_usage: Literal["TEAR_TOP", "POSITIONS"] = "TEAR_TOP"
    signature_lines: Literal[1, 2] = 1          # 2.0.0 (#167): one or two signature lines
    stock_note: str | None = Field(default=None, max_length=200)
    outline: list[OutlineItem] = Field(default_factory=list, max_length=80)

    @model_validator(mode="after")
    def _check(self):
        if (self.paper_width, self.paper_height) != LETTER:
            raise ValueError("Only Letter (8.5 x 11 in) check sheets are supported.")
        if self.check_width > self.paper_width:
            raise ValueError("The check is wider than the sheet.")
        prev_end = 0.0
        for top in self.check_tops:
            if top < prev_end - 1e-6:
                raise ValueError("Checks on the sheet overlap or are out of order.")
            if top + self.check_height > self.paper_height + 1e-6:
                raise ValueError("A check runs past the bottom of the sheet.")
            prev_end = top + self.check_height
        self.check_tops = [_r(t) for t in self.check_tops]
        return self


class Defaults(_M):
    font: str = "SANS"
    size: float = Field(default=10, ge=fonts.MIN_SIZE, le=fonts.MAX_SIZE)
    upper: bool = True

    @field_validator("font")
    @classmethod
    def _font(cls, v):
        if v not in fonts.FONTS:
            raise ValueError("Unknown font: choose one of the built-in fonts.")
        return v


class Box(_M):
    x: float = Inch
    y: float = Inch
    w: float = Field(ge=0.2, le=8.5)
    h: float = Field(ge=0.1, le=3)


class TextField(Box):
    font: str | None = None
    size: float | None = Field(default=None, ge=fonts.MIN_SIZE, le=fonts.MAX_SIZE)
    bold: bool = False
    upper: bool | None = None
    align: Literal["LEFT", "CENTER", "RIGHT"] = "LEFT"
    shrink: bool = True                                  # step the size down to fit before warning
    min_size: float = Field(default=8, ge=fonts.MIN_SIZE, le=fonts.MAX_SIZE)

    @field_validator("font")
    @classmethod
    def _font(cls, v):
        if v is not None and v not in fonts.FONTS:
            raise ValueError("Unknown font: choose one of the built-in fonts.")
        return v


class Fields(_M):
    date: TextField
    payee: TextField
    amount_number: TextField
    amount_words: TextField
    memo: TextField
    signature: Box
    signature2: Box | None = None          # 2.0.0 (#167): the second signature line (two-line styles)


class AmountWords(_M):
    and_mode: Literal["CENTS", "HUNDREDS"] = "CENTS"      # bank convention: AND only before the cents
    hyphens: bool = True
    case: Literal["UPPER", "TITLE", "LOWER"] = "UPPER"
    cents: Literal["NN", "NO"] = "NN"                     # whole dollars: 00/100 or NO/100
    fill: Literal["DOTS", "DASHES", "LINE", "STARS"] = "DOTS"
    fill_placement: Literal["BETWEEN", "AFTER"] = "BETWEEN"
    trailing_word: str = Field(default="", max_length=20)

    @field_validator("trailing_word")
    @classmethod
    def _tw(cls, v):
        v = v.strip()
        if v and not re.fullmatch(r"[A-Za-z]+", v):
            raise ValueError("The trailing word may contain letters only.")
        return v


class AmountNumber(_M):
    commas: bool = True
    dollar_sign: bool = False
    lead_fill: Literal["", "*", "**", "***"] = "**"


class FeedMode(_M):
    key: str = Field(pattern=r"^[a-z0-9_]{1,20}$")
    label: str = Field(min_length=1, max_length=60)
    kind: Literal["SHEET", "SINGLE"]
    position: int = Field(default=0, ge=0, le=2)                       # SHEET: which check on the sheet (0 = top)
    lead: Literal["DATE_END", "PAYTO_END"] = "DATE_END"              # SINGLE: which end feeds first
    page: Literal["LETTER", "CHECK"] = "LETTER"                      # SINGLE: page size sent to the printer
    guide: Literal["CENTER", "LEFT", "RIGHT"] = "CENTER"             # SINGLE + LETTER: where the guides hold it
    dx: float = Field(default=0, ge=-FEED_OFFSET_MAX, le=FEED_OFFSET_MAX)   # offset in check coordinates
    dy: float = Field(default=0, ge=-FEED_OFFSET_MAX, le=FEED_OFFSET_MAX)
    note: str | None = Field(default=None, max_length=200)           # printer note, e.g. which driver profile


class StubColumn(_M):
    key: Literal["INVOICE", "INVOICE_DATE", "DESCRIPTION", "BUDGET", "NOTES", "AMOUNT"]
    heading: str = Field(min_length=1, max_length=40)


def default_stub_columns() -> list[StubColumn]:
    return [StubColumn(key="INVOICE", heading="Invoice #"), StubColumn(key="INVOICE_DATE", heading="Invoice Date"),
            StubColumn(key="DESCRIPTION", heading="Description"), StubColumn(key="AMOUNT", heading="Amount")]


class Stub(_M):
    """2.0.0 (#167): a detail stub of a voucher check, in page inches from the sheet's top edge. Its content flows in
    a fixed order: title and CHECK #, payee / date / amount, the line table and total, the memo. The vendor copy never
    shows budgets; the office copy adds the budget column and OFFICE COPY."""
    top: float = Field(ge=0, le=11)
    height: float = Field(ge=STUB_MIN_HEIGHT, le=11)
    copy_kind: Literal["VENDOR", "OFFICE"] = "VENDOR"
    title: str = Field(default="{ORG}", max_length=200)          # a pattern (patterns.STUB)
    show_check_number: bool = True
    font: str = "SANS"
    size: float = Field(default=9, ge=6, le=12)
    margin: float = Field(default=0.4, ge=0.1, le=1.5)            # left and right, inches
    show_memo: bool = True

    @field_validator("font")
    @classmethod
    def _font(cls, v):
        if v not in fonts.FONTS:
            raise ValueError("Unknown font: choose one of the built-in fonts.")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        from . import patterns
        patterns.parse(v, patterns.STUB)
        return v


class StyleConfig(_M):
    stock: Stock
    defaults: Defaults = Field(default_factory=Defaults)
    fields: Fields
    amount_words: AmountWords = Field(default_factory=AmountWords)
    amount_number: AmountNumber = Field(default_factory=AmountNumber)
    date_format: Literal["MM/DD/YYYY", "MM/DD/YY", "YYYY-MM-DD", "MONTH D, YYYY"] = "MM/DD/YYYY"
    memo_default: str = Field(default="", max_length=200)
    signature_limit_cents: int | None = Field(default=None, ge=1, le=99_999_999_999)
    default_signer_id: int | None = None
    # 2.0.0 (#167): two-line styles - above this amount only the first signature prints (the second line is signed
    # by hand); above signature_limit_cents neither prints
    second_line_limit_cents: int | None = Field(default=None, ge=1, le=99_999_999_999)
    default_signer2_id: int | None = None
    stubs: list[Stub] = Field(default_factory=list, max_length=MAX_STUBS)
    stub_columns: list[StubColumn] = Field(default_factory=default_stub_columns, min_length=1, max_length=6)
    feed_modes: list[FeedMode] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def _check(self):
        cw, ch = self.stock.check_width, self.stock.check_height
        limit = ch - CLEAR_ZONE
        two = self.stock.signature_lines == 2
        if two and self.fields.signature2 is None:
            raise ValueError("Second signature: place the second signature line.")
        if not two:
            self.fields.signature2 = None
            if self.second_line_limit_cents is not None or self.default_signer2_id is not None:
                raise ValueError("The second-line limit and second default signer need two signature lines.")
        if (self.second_line_limit_cents is not None and self.signature_limit_cents is not None
                and self.second_line_limit_cents >= self.signature_limit_cents):
            raise ValueError("The second-line limit must be below the no-signature limit.")
        if self.default_signer_id is not None and self.default_signer_id == self.default_signer2_id:
            raise ValueError("The two default signers must be different people.")
        for name in (*TEXT_FIELDS, "signature", *(("signature2",) if two else ())):
            b = getattr(self.fields, name)
            label = FIELD_LABELS[name]
            if b.x + b.w > cw + 1e-6:
                raise ValueError(f"{label}: the field runs past the right edge of the check.")
            if b.y + b.h > limit + 1e-6:
                raise ValueError(f"{label}: the field reaches into the bottom 5/8 inch of the check, which must "
                                 f"stay clear for the bank numbers.")
            for k in ("x", "y", "w", "h"):
                setattr(b, k, _r(getattr(b, k)))
            if name in TEXT_FIELDS and b.min_size > (b.size or self.defaults.size):
                raise ValueError(f"{label}: the smallest size is larger than the font size.")
        keys = [m.key for m in self.feed_modes]
        if len(set(keys)) != len(keys):
            raise ValueError("Each feed mode needs its own key.")
        for m in self.feed_modes:
            if m.kind == "SHEET" and m.position >= len(self.stock.check_tops):
                raise ValueError(f"Feed mode '{m.label}': there is no check at that position on the sheet.")
            if m.kind == "SINGLE" and ch > 8.5:
                raise ValueError(f"Feed mode '{m.label}': the check is too long to feed on its own.")
            m.dx, m.dy = _r(m.dx), _r(m.dy)
        if not any(m.kind == "SHEET" for m in self.feed_modes):
            raise ValueError("At least one sheet feed mode is required.")
        if two:
            a, b = self.fields.signature, self.fields.signature2
            if a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h:
                raise ValueError("The two signature lines overlap.")
        if self.stubs:
            self._check_stubs()
        keys = [c.key for c in self.stub_columns]
        if len(set(keys)) != len(keys):
            raise ValueError("Each stub column can be used once.")
        for o in self.stock.outline:
            for v, lim in ((o.x, cw), (o.x2, cw), (o.y, ch), (o.y2, ch)):
                if v is not None and v > lim + 1e-6:
                    raise ValueError("A stock outline item lies outside the check.")
        return self

    def _check_stubs(self) -> None:
        if len(self.stock.check_tops) != 1:
            raise ValueError("A voucher style has one check per sheet.")
        if any(m.kind != "SHEET" for m in self.feed_modes):
            raise ValueError("A voucher style prints whole sheets: single-check feed modes are not available.")
        top = self.stock.check_tops[0]
        areas = [(top, top + self.stock.check_height, "the check")]
        for i, st in enumerate(sorted(self.stubs, key=lambda x: x.top)):
            st.top, st.height = _r(st.top), _r(st.height)
            end = st.top + st.height
            if end > self.stock.paper_height + 1e-6:
                raise ValueError(f"Stub {i + 1} runs past the bottom of the sheet.")
            if 2 * st.margin >= self.stock.paper_width - 2:
                raise ValueError(f"Stub {i + 1}: the margins leave no room for the content.")
            for a0, a1, what in areas:
                if st.top < a1 - 1e-6 and a0 < end - 1e-6:
                    raise ValueError(f"Stub {i + 1} overlaps {what}.")
            areas.append((st.top, end, f"stub {i + 1}"))

    # --------------------------------------------------------------- helpers
    def feed(self, key: str) -> FeedMode | None:
        return next((m for m in self.feed_modes if m.key == key), None)

    def field_font(self, name: str) -> tuple[str, float, bool, bool]:
        """(font key, size, bold, upper) of a text field, with the check-wide defaults filled in."""
        f: TextField = getattr(self.fields, name)
        return (f.font or self.defaults.font, f.size or self.defaults.size, f.bold,
                self.defaults.upper if f.upper is None else f.upper)


def parse(data: dict) -> StyleConfig:
    return StyleConfig.model_validate(data)
