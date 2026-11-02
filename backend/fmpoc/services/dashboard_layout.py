"""v1.5.0 CR-031: order and visibility of the dashboard sections, saved per user.

Stored in ``app_user.dashboard_layout`` as a comma list of section keys in display order; a hidden section is
prefixed with ``-`` (e.g. ``fiscal_year,bank,-budget,attention,charts,review``). NULL = the default layout.
Unknown keys are dropped; sections missing from a saved layout (e.g. added in a later version) are appended,
visible, in their default position order.
"""
from __future__ import annotations

# default order: the 1.4.1 layout, with due reminders on top since v1.6.3 (CR-036; shown only when there are any)
# 2.4.0 (#255): "invoices" - the overdue invoices card (shown when the Invoices module is on)
SECTIONS = ["notifications", "fiscal_year", "budget", "review", "bank", "attention", "invoices", "charts"]


def layout_for(user) -> list[dict]:
    raw = getattr(user, "dashboard_layout", None)
    out: list[dict] = []
    seen: set[str] = set()
    for item in (raw or "").split(","):
        item = item.strip()
        key = item.lstrip("-")
        if key in SECTIONS and key not in seen:
            seen.add(key)
            out.append({"key": key, "visible": not item.startswith("-")})
    out += [{"key": k, "visible": True} for k in SECTIONS if k not in seen]
    return out


def encode(items) -> str | None:
    seen: set[str] = set()
    parts: list[str] = []
    for it in items:
        if it.key in seen:
            continue
        seen.add(it.key)
        parts.append(it.key if it.visible else f"-{it.key}")
    parts += [k for k in SECTIONS if k not in seen]
    return ",".join(parts)


def is_customized(user) -> bool:
    return getattr(user, "dashboard_layout", None) is not None
