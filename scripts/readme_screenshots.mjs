// Takes the screenshots used in README.md from a demo organization (scripts/demo_data.py).
//
//   1. Start a NEW, empty PennyWarden (never one with real data):
//        cd backend && python -m fmpoc --no-browser --port 8801 --data-dir /tmp/pennywarden-demo
//   2. python scripts/demo_data.py http://127.0.0.1:8801
//   3. node scripts/readme_screenshots.mjs http://127.0.0.1:8801        (needs `npm --prefix frontend ci`)
//
// Writes docs/screenshots/readme/*.png, including pages of the sample PDFs (needs `pdftoppm` from poppler for those).
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(join(ROOT, "frontend", "package.json"));
const { chromium } = require("@playwright/test");
const BASE = (process.argv[2] || "http://127.0.0.1:8801").replace(/\/$/, "");
const OUT = join(ROOT, "docs", "screenshots", "readme");
const PASSWORD = "Demo-PennyWarden-2026";
mkdirSync(OUT, { recursive: true });
const TMP = mkdtempSync(join(tmpdir(), "pennywarden-shots-"));

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1360, height: 850 }, baseURL: BASE });
const page = await ctx.newPage();
const nav = page.getByRole("navigation", { name: "Main navigation" });
// The page scrolls inside the application shell, so a taller window is used instead of a "full page" capture.
const shot = async (name, height = 850) => {
  await page.setViewportSize({ width: 1360, height });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(900); // charts animate in
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  await page.setViewportSize({ width: 1360, height: 850 });
  console.log("wrote", name);
};
// 2.0.0: just the dialog, without the dimmed page behind it
const dialogShot = async (dialog, name, height) => {
  await page.setViewportSize({ width: 1360, height: 1100 });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  const box = await dialog.boundingBox();
  await page.screenshot({ path: join(OUT, `${name}.png`), clip: { x: box.x, y: box.y, width: box.width, height: Math.min(box.height, height) } });
  await page.setViewportSize({ width: 1360, height: 850 });
  console.log("wrote", name);
};
const go = async (link) => { await nav.getByRole("link", { name: link }).click(); await page.waitForLoadState("networkidle"); };

await page.goto("/");
await page.getByLabel("Username").fill("treasurer");
await page.getByLabel("Password").fill(PASSWORD);
await page.getByRole("button", { name: "Sign in" }).click();
await nav.waitFor();

await shot("dashboard", 1610);
await go("Budgets"); await shot("budgets");
await go("Register"); await shot("register");
await go("Fiscal Years");
await page.getByRole("link", { name: /^(FY)?\d{4}/ }).first().click();
await shot("fiscal-year", 1300);
await go("Fundraisers");
await page.getByRole("link", { name: /Spring Concert/ }).first().click();
await shot("fundraiser", 1300);
await go(/Notifications/).catch(async () => { await page.goto("/notifications"); });
await shot("reminders");
await page.getByRole("button", { name: "New reminder" }).click();
const dlg = page.getByRole("dialog", { name: "New reminder" });
await dlg.getByRole("combobox").first().selectOption("ORGANIZATION");
await dlg.getByLabel("Reminder", { exact: true }).fill("Send the monthly treasurer's report");
await dlg.getByRole("combobox", { name: "Repeat", exact: true }).selectOption("yes");
await shot("reminder-repeat");
await dlg.getByRole("button", { name: "Cancel" }).click();
await go("Reports"); await shot("reports");
await go("Dashboard");
await page.getByRole("button", { name: "Switch to dark mode" }).click();
await shot("dashboard-dark", 1610);
await page.getByRole("button", { name: "Switch to light mode" }).click();

// 2.0.0: the Payments module - a bill entered once, then its check on the print screen (nothing is printed)
await go("Payments");
await page.getByRole("button", { name: "New payment" }).click();
const pay = page.getByRole("dialog", { name: /^New payment – / });
await pay.getByRole("combobox", { name: "Payee (entity)" }).fill("Harmony Music");
await page.getByRole("option", { name: /Harmony Music Supply/ }).click();
await pay.getByRole("button", { name: "More than one invoice" }).click();
const repairs = await pay.getByLabel("Allocation 1 Budget").locator("option", { hasText: "5000" }).first().getAttribute("value");
for (const [i, inv, desc, amt] of [[1, "H-2516", "Sousaphone dent repair", "385.00"], [2, "H-2521", "Reeds, valve oil, mouthpieces", "142.80"]]) {
  await pay.getByLabel(`Allocation ${i} Budget`).selectOption(repairs);
  await pay.getByLabel(`Allocation ${i} Amount`).fill(amt);
  await pay.locator(".alloc").nth(i - 1).getByLabel("Invoice #").fill(inv);
  await pay.locator(".alloc").nth(i - 1).getByLabel("Description").fill(desc);
}
await pay.getByLabel("Check #").fill("1068");
await page.evaluate(() => document.activeElement?.blur());
await pay.getByTestId("amount-preview").getByText(/FIVE HUNDRED TWENTY-SEVEN/).waitFor();
await dialogShot(pay, "payment", 892);
await pay.getByRole("button", { name: "Save and print check" }).click();
const prt = page.getByRole("dialog", { name: /^Print check – transaction #\d+$/ });
await prt.getByRole("img", { name: "Check preview drawn to scale" }).waitFor();
await dialogShot(prt, "check-print", 760);
await prt.getByRole("button", { name: "Close" }).first().click();

// sample PDFs -> page images
const pdf = async (url, name, pages) => {
  const r = await ctx.request.get(url);
  if (!r.ok()) throw new Error(`${url} -> ${r.status()}`);
  const file = join(TMP, `${name}.pdf`);
  writeFileSync(file, await r.body());
  for (const [label, n] of Object.entries(pages)) {
    execFileSync("pdftoppm", ["-r", "110", "-f", String(n), "-l", String(n), "-singlefile", "-png", file, join(OUT, `${name}-${label}`)]);
  }
  console.log("wrote", name);
};
const fy = (await (await ctx.request.get("/api/fiscal-years")).json())[0].id;
const fr = (await (await ctx.request.get("/api/fundraisers")).json());
await pdf(`/api/reports/audit?fiscal_year_id=${fy}&signature_page=true`, "audit-report", { cover: 1, review: 2, budgets: 3, account: 4, transaction: 5 });
const frId = (fr.items || fr)[0].id;
await pdf(`/api/fundraisers/${frId}/count-sheet`, "count-sheet", { page: 1 });
await browser.close();
