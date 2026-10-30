"""2.2.0 (#317): dotted entity variables by role - {PAYEE.*} on checks, stubs, letters and envelopes, {DONOR.*} on
receipts and year-end statements ({ORG.*} is the organization profile, #314). The display name and the mailing address
never come out blank: they fall back to the name and the address (#315)."""
from __future__ import annotations

from .. import phone as phone_fmt

FIELDS: dict[str, str] = {
    "NAME": "name (as printed on checks, envelopes and letters)",
    "DISPLAY_NAME": "display name (the name when none is set)",
    "FIRST_NAME": "first name (the person, or an organization's contact person)",
    "LAST_NAME": "last name",
    "ADDRESS": "address, several lines",
    "MAILING_ADDRESS": "mailing address, several lines (the address when none is set)",
    "ADDRESS1": "street address", "ADDRESS2": "address, second line", "CITY": "city", "STATE": "state",
    "ZIP": "ZIP code", "COUNTRY": "country", "PHONE": "phone", "EMAIL": "email", "EIN": "EIN (organizations)",
    "ENTITY_NUMBER": "Entity Number, e.g. ENT-000123",
}
MULTILINE_FIELDS = ("ADDRESS", "MAILING_ADDRESS")
ROLES = {"PAYEE": "Payee's", "DONOR": "Donor's"}


def values(role: str, e) -> dict[str, str]:
    """{ROLE.FIELD: text} for one entity (empty strings without one)."""
    from .checkprint.service import address_lines
    if e is None:
        return {f"{role}.{k}": "" for k in FIELDS}
    v = {"NAME": e.legal_name, "DISPLAY_NAME": e.display_name, "FIRST_NAME": e.first_name or "",
         "LAST_NAME": e.last_name or "", "ADDRESS": "\n".join(address_lines(e, mailing=False)),
         "MAILING_ADDRESS": "\n".join(address_lines(e)), "ADDRESS1": e.address_line1 or "",
         "ADDRESS2": e.address_line2 or "", "CITY": e.city or "", "STATE": e.state_region or "",
         "ZIP": e.postal_code or "", "COUNTRY": e.country or "", "PHONE": phone_fmt.display(e.phone) or "",
         "EMAIL": e.email or "", "EIN": e.ein or "", "ENTITY_NUMBER": e.entity_number or ""}
    return {f"{role}.{k}": (x or "").strip() if k not in MULTILINE_FIELDS else x for k, x in v.items()}


SAMPLE_PERSON = {"NAME": "SAMPLE DONOR", "DISPLAY_NAME": "SAMPLE DONOR", "FIRST_NAME": "SAMPLE", "LAST_NAME": "DONOR",
                 "ADDRESS": "123 Main Street\nSample Town, US 55555",
                 "MAILING_ADDRESS": "123 Main Street\nSample Town, US 55555", "ADDRESS1": "123 Main Street",
                 "ADDRESS2": "", "CITY": "Sample Town", "STATE": "US", "ZIP": "55555", "COUNTRY": "",
                 "PHONE": "(555) 555-0100", "EMAIL": "donor@example.org", "EIN": "", "ENTITY_NUMBER": "ENT-000000"}


def sample(role: str, name: str, address: list[str]) -> dict[str, str]:
    v = {**SAMPLE_PERSON, "NAME": name, "DISPLAY_NAME": name, "ADDRESS": "\n".join(address),
         "MAILING_ADDRESS": "\n".join(address), "ADDRESS1": address[0] if address else ""}
    return {f"{role}.{k}": x for k, x in v.items()}


def addressee(lines: list[str], vals: dict, context: str) -> list[str]:
    """The addressee block: each configured line resolved, several-line values split, empty lines left out."""
    from .checkprint import patterns
    out: list[str] = []
    for line in lines:
        text = patterns.resolve(line, vals, context).text
        out += [x.strip() for x in text.split("\n") if x.strip()]
    return out
