/** 2.4.0 (#473, book #488): the user guide is bundled into the app at build time, so Help shows the guide of the
 * installed version and works without an internet connection (BR-DOC-001). Only project-authored Markdown is bundled;
 * it is rendered as React elements (escaped text, no raw HTML - BR-096). The book itself is in helpDocs.ts, loaded only
 * when Help opens, so the rest of the app doesn't carry it. */
/** Where Markdown links to other repository files go (they are not bundled): the source on GitHub. */
export const REPO_BLOB = "https://github.com/kretherford0983/PennyWarden/blob/main/";

/** Page (first path segment) -> the guide page that describes it, as "<chapter>/<page>" (BR-DOC-002).
 * test_v240_user_guide.py checks every one exists in docs/guide/guide.json. */
export const HELP_SECTIONS: Record<string, string> = {
  "/": "dashboard/dashboard",
  "/account": "my-account/my-account",
  "/fiscal-years": "fiscal-years/fiscal-year-page",
  "/budgets": "budgets/about-budgets",
  "/bank-accounts": "bank-accounts/set-up-account",
  "/entities": "entities/entities",
  "/register": "register/read-register",
  "/reports": "reports/reports-catalog",
  "/fundraisers": "events/about-events",
  "/fundraiser-series": "events/event-reports",
  "/payments": "payments/payments-overview",
  "/check-setup": "payments/payments-setup",
  "/donations": "donations/donation-receipts",
  "/donation-setup": "donations/donations-setup",
  "/invoices": "invoices/about-invoices",
  "/invoice-setup": "invoices/invoices-setup",
  "/notifications": "notifications/reminders",
  "/envelopes": "envelopes-and-signers/envelopes",
  "/signers": "envelopes-and-signers/signers",
  "/users": "users/manage-users",
  "/audit-log": "audit-log/audit-log",
  "/about": "system-about/system-about-tabs",
};

/** The help address for the page at `path`. A page the user may not open gets the guide's contents, so no help link
 * points at a module hidden from the user's role (AC-DOC-004). */
export function helpFor(path: string, allowed: (base: string) => boolean): string {
  const base = path === "/" ? "/" : "/" + path.split("/")[1];
  const target = HELP_SECTIONS[base];
  if (!target || (base !== "/account" && base !== "/notifications" && base !== "/about" && !allowed(base))) return "/help";
  return `/help/${target}`;
}
