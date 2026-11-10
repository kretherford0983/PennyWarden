/** 2.4.0 (#551): the app functions a reminder task can open - every report of the report registry and the main pages.
 * A task stores the id ("report:<id>" / "page:<name>"); the name shown is always the one users see in the app (the
 * report's name on the Reports page, the page's name in the left navigation), looked up here so a rename follows.
 * The server keeps the same ids (backend services/reminder_tasks.py, checked by a test). */
import { REPORTS, reportPath, type ReportCtx } from "./pages/reports/registry";

/** The left navigation's names for these pages (App.tsx navFor uses them too). */
export const PAGE_NAMES: Record<string, string> = {
  "/fiscal-years": "Fiscal Years", "/budgets": "Budgets", "/bank-accounts": "Bank Accounts", "/register": "Register",
  "/payments": "Payments", "/donations": "Donations", "/invoices": "Invoices", "/entities": "Entities",
  "/fundraisers": "Events", "/reports": "Reports",
};

export const PAGE_FUNCTIONS: { id: string; path: string }[] = [
  { id: "page:fiscal-years", path: "/fiscal-years" }, { id: "page:budgets", path: "/budgets" },
  { id: "page:bank-accounts", path: "/bank-accounts" }, { id: "page:register", path: "/register" },
  { id: "page:payments", path: "/payments" }, { id: "page:donations", path: "/donations" },
  { id: "page:invoices", path: "/invoices" }, { id: "page:entities", path: "/entities" },
  { id: "page:events", path: "/fundraisers" }, { id: "page:reports", path: "/reports" },
];

export type AppFunction = { id: string; kind: "report" | "page"; name: string; path: string;
  usable: (c: ReportCtx, allowedPaths: Set<string>) => boolean };

export const FUNCTIONS: AppFunction[] = [
  ...REPORTS.map((r): AppFunction => ({ id: `report:${r.id}`, kind: "report", name: r.name, path: reportPath(r.id),
    usable: (c, allowed) => allowed.has("/reports") && r.visible(c) })),
  ...PAGE_FUNCTIONS.map((p): AppFunction => ({ id: p.id, kind: "page", name: PAGE_NAMES[p.path], path: p.path,
    usable: (_c, allowed) => allowed.has(p.path) })),
];

export function functionFor(id: string | null | undefined): AppFunction | undefined {
  return id ? FUNCTIONS.find((f) => f.id === id) : undefined;
}
