/** 2.4.0 (#473): the user guide is bundled into the app at build time, so Help shows the guide of the installed
 * version and works without an internet connection (BR-DOC-001). Only project-authored Markdown is bundled here;
 * it is rendered as React elements (escaped text, no raw HTML - BR-096). The documents themselves are in helpDocs.ts,
 * loaded only when Help opens, so the rest of the app doesn't carry them. */
/** Where Markdown links to other repository files go (they are not bundled): the source on GitHub. */
export const REPO_BLOB = "https://github.com/kretherford0983/PennyWarden/blob/main/";

/** Page (first path segment) -> the user guide section that describes it (BR-DOC-002). The anchors are the fixed
 * `<a id="...">` markers in docs/user-guide.md; test_v240_user_guide.py checks every one exists. */
export const HELP_SECTIONS: Record<string, string> = {
  "/": "dashboard",
  "/account": "my-account",
  "/fiscal-years": "fiscal-years",
  "/budgets": "budgets",
  "/bank-accounts": "bank-accounts",
  "/entities": "entities",
  "/register": "register",
  "/reports": "reports",
  "/fundraisers": "events",
  "/fundraiser-series": "events",
  "/payments": "payments",
  "/check-setup": "payments",
  "/donations": "donations",
  "/donation-setup": "donations",
  "/invoices": "invoices",
  "/invoice-setup": "invoices",
  "/notifications": "notifications",
  "/envelopes": "envelopes",
  "/signers": "envelopes",
  "/users": "users",
  "/audit-log": "audit-log",
  "/about": "system-about",
};

/** The help address for the page at `path`. A page the user may not open gets the start of the guide, so no help
 * link points at a module hidden from the user's role (AC-DOC-004). */
export function helpFor(path: string, allowed: (base: string) => boolean): string {
  const base = path === "/" ? "/" : "/" + path.split("/")[1];
  const section = HELP_SECTIONS[base];
  if (!section || (base !== "/account" && base !== "/notifications" && base !== "/about" && !allowed(base))) return "/help";
  return `/help#${section}`;
}
