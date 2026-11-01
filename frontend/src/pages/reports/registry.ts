/** 2.3.0 (#375): the one report registry. It drives the Reports catalog, the side list, search, deep links
 * (/reports/<id>), permission and module hiding, recently run and the shortcuts from other screens - adding a report is
 * one entry here (and its component in Reports.tsx). The ids are the server's too (services/report_prefs.py). */

export type Output = "PDF" | "PPTX" | "CSV" | "Screen";
export type GroupId = "share" | "audit" | "analyze" | "plan" | "fundraisers" | "invoices";
export type ReportCtx = { can: (p: string) => boolean; modules: Record<string, boolean | undefined> };
export type ReportDef = {
  id: string; name: string; short: string; purpose: string; audience: string; group: GroupId; outputs: Output[];
  keywords?: string; visible: (c: ReportCtx) => boolean;
};

/** Grouped by purpose (first iteration; admin-configurable grouping is #376). */
export const GROUPS: { id: GroupId; name: string; short: string; why: string }[] = [
  { id: "share", name: "Share with the board and members", short: "Share", why: "documents for meetings" },
  { id: "audit", name: "Audit and year-end close", short: "Audit and close", why: "the records an auditor reviews" },
  { id: "analyze", name: "Analyze activity", short: "Analyze", why: "where money came from and went" },
  { id: "plan", name: "Plan budgets", short: "Plan", why: "next year's numbers" },
  { id: "fundraisers", name: "Fundraisers", short: "Fundraisers", why: "event-day paperwork" },
  { id: "invoices", name: "Invoices", short: "Invoices", why: "what customers owe and have paid" },   // 2.4.0 (#255)
];

const financial = (c: ReportCtx) => c.can("financial.view");
const fundraisers = (c: ReportCtx) => !!c.modules.fundraisers && c.can("financial.view");
const budgets = (c: ReportCtx) => c.can("budget.manage");
const invoices = (c: ReportCtx) => !!c.modules.invoices && c.can("invoice.view");

export const REPORTS: ReportDef[] = [
  { id: "quarterly", name: "Quarterly / Annual financial report", short: "Quarterly / Annual", group: "share", outputs: ["PDF", "PPTX"],
    purpose: "Accounts, cash flow, budgets and fundraisers as of the end of a quarter or year, with last year beside them.",
    audience: "Board and members", keywords: "board quarter annual presentation deck", visible: financial },
  { id: "fundraising-fy", name: "Fiscal Year fundraising report", short: "FY fundraising", group: "share", outputs: ["PDF", "PPTX"],
    purpose: "The year's fundraisers with the history of their series, trends and averages.",
    audience: "Board and members", keywords: "fundraiser series history deck", visible: fundraisers },
  { id: "audit", name: "End of Year Audit", short: "End of Year Audit", group: "audit", outputs: ["PDF"],
    purpose: "The year's budgets and every register transaction with its attachments, account by account.",
    audience: "Auditors", keywords: "transactions attachments signature", visible: financial },
  { id: "close", name: "Fiscal Year Close", short: "Fiscal Year Close", group: "audit", outputs: ["PDF"],
    purpose: "The audit report with the year's approval, audit sign-off and other Fiscal Year documents.",
    audience: "Auditors and Budget Managers", keywords: "closing documents", visible: financial },
  { id: "fundraiser-detail", name: "Fundraiser detail (audit)", short: "Fundraiser detail", group: "audit", outputs: ["PDF"],
    purpose: "One fundraiser's lines, buckets, excluded lines with reasons, and its documents.",
    audience: "Auditors", keywords: "fundraiser lines buckets", visible: fundraisers },
  { id: "entity", name: "Entity activity", short: "Entity activity", group: "analyze", outputs: ["Screen", "CSV"],
    purpose: "How much each vendor, donor or organization deposited and withdrew in a period.",
    audience: "Treasurer and Budget Managers", keywords: "vendor donor totals", visible: financial },
  { id: "flow", name: "Financial Flow", short: "Financial Flow", group: "analyze", outputs: ["PDF"],
    purpose: "Money in and out of an account line by line, reviewed and annotated before printing.",
    audience: "Treasurer", keywords: "cash in out lines", visible: financial },
  { id: "budget-review", name: "Budget Review", short: "Budget Review", group: "plan", outputs: ["PDF", "CSV"],
    purpose: "Each budget over the years - budgeted, actual and projected - to plan the next one.",
    audience: "Budget Managers", keywords: "history projection prep", visible: budgets },
  { id: "planning-sheet", name: "Planning Sheet", short: "Planning Sheet", group: "plan", outputs: ["PDF"],
    purpose: "The printed form for the budget planning meeting, with blank columns for the proposed amounts.",
    audience: "Budget Managers", keywords: "meeting proposed form", visible: budgets },
  { id: "count-sheet", name: "Cash count sheet", short: "Cash count sheet", group: "fundraisers", outputs: ["PDF"],
    purpose: "The form to count the cash and checks of an event and sign for them.",
    audience: "Event volunteers", keywords: "cash count signatures", visible: fundraisers },
  // 2.4.0 (#255): the Invoices group
  { id: "inv-open", name: "Open invoices", short: "Open invoices", group: "invoices", outputs: ["Screen", "PDF", "CSV"],
    purpose: "Every invoice with a balance still open on a date, with what has been paid and what is overdue.",
    audience: "Invoice Managers and the treasurer", keywords: "unpaid receivable owed outstanding", visible: invoices },
  { id: "inv-aging", name: "Aging", short: "Aging", group: "invoices", outputs: ["Screen", "PDF", "CSV"],
    purpose: "What each customer owes, by how long it is past due: current, 1–30, 31–60, 61–90 and over 90 days.",
    audience: "Invoice Managers and the treasurer", keywords: "receivable overdue days buckets", visible: invoices },
  { id: "inv-statement", name: "Customer statement", short: "Customer statement", group: "invoices", outputs: ["Screen", "PDF"],
    purpose: "One customer's invoices, payments and credits in a period and what they still owe - to send them.",
    audience: "Customers", keywords: "account balance owed", visible: invoices },
  { id: "inv-sales-tax", name: "Sales tax collected", short: "Sales tax", group: "invoices", outputs: ["Screen", "PDF", "CSV"],
    purpose: "Tax charged on invoices and collected with payments, per tax rate, for a sales tax return.",
    audience: "Treasurer", keywords: "tax return filing rate", visible: invoices },
  { id: "inv-register", name: "Invoice register", short: "Invoice register", group: "invoices", outputs: ["Screen", "PDF", "CSV"],
    purpose: "Every invoice dated in a period with its status, total, payments and revisions.",
    audience: "Auditors and Invoice Managers", keywords: "list all invoices status void written off", visible: invoices },
  { id: "inv-sales", name: "Sales by product / category", short: "Sales by product", group: "invoices", outputs: ["Screen", "PDF", "CSV"],
    purpose: "Quantities and amounts invoiced by product, category or Income budget.",
    audience: "Budget Managers and Invoice Managers", keywords: "products categories revenue budget", visible: invoices },
  { id: "inv-activity", name: "Payments, write-offs, discounts and refunds", short: "Payments and write-offs", group: "invoices",
    outputs: ["Screen", "PDF", "CSV"], purpose: "Money received and refunded, amounts written off (self-approved marked) and discounts given in a period.",
    audience: "Auditors and Budget Managers", keywords: "payments refunds write-off discount self-approved", visible: invoices },
];

export const reportPath = (id: string) => `/reports/${id}`;

export function visibleReports(c: ReportCtx): ReportDef[] {
  return REPORTS.filter((r) => r.visible(c));
}

export function searchReports(list: ReportDef[], q: string): ReportDef[] {
  const t = q.trim().toLowerCase();
  if (!t) return list;
  return list.filter((r) => `${r.name} ${r.purpose} ${r.audience} ${r.keywords || ""}`.toLowerCase().includes(t));
}
