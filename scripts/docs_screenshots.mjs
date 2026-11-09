// 2.4.0 (#488): takes the screenshots used in the user guide (docs/guide/img/*.png) from the made-up demo organization.
// Re-run it for every release, so the pictures match the version the guide describes.
//
//   1. Start a NEW, empty PennyWarden (never one with real data):
//        cd backend && python -m fmpoc --no-browser --port 8801 --data-dir /tmp/pennywarden-docs
//   2. python scripts/demo_data.py http://127.0.0.1:8801 && python scripts/docs_data.py http://127.0.0.1:8801
//   3. node scripts/docs_screenshots.mjs http://127.0.0.1:8801        (needs `npm --prefix frontend ci`)
//
// Everything shown is invented (BR: screenshots in the repository hold synthetic data only). A shot that fails is
// reported and skipped; the script exits non-zero at the end if any failed.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(join(ROOT, "frontend", "package.json"));
const { chromium } = require("@playwright/test");
const BASE = (process.argv[2] || "http://127.0.0.1:8801").replace(/\/$/, "");
const OUT = join(ROOT, "docs", "guide", "img");
const PASSWORD = "Demo-PennyWarden-2026";
const W = 1280;
mkdirSync(OUT, { recursive: true });

const launch = process.env.PW_CHROME ? { executablePath: process.env.PW_CHROME, args: ["--no-sandbox", "--disable-gpu"] } : {};
const browser = await chromium.launch(launch);
const ctx = await browser.newContext({ viewport: { width: W, height: 800 }, baseURL: BASE, colorScheme: "light" });
const page = await ctx.newPage();
const nav = page.getByRole("navigation", { name: "Main navigation" });
const failed = [];

const settle = async () => { await page.waitForLoadState("networkidle"); await page.waitForTimeout(700); };
/** The whole window at `height` (the app scrolls inside its shell, so a taller window shows more). */
const shot = async (name, height = 800) => {
  await page.setViewportSize({ width: W, height });
  await settle();
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  await page.setViewportSize({ width: W, height: 800 });
  console.log("wrote", name);
};
/** Just one element (a dialog, a card), cropped to at most `max` px high. */
const part = async (locator, name, max = 900) => {
  await page.setViewportSize({ width: W, height: 1200 });
  await settle();
  const box = await locator.first().boundingBox();
  if (!box) throw new Error(`nothing to capture for ${name}`);
  await page.screenshot({ path: join(OUT, `${name}.png`), clip: { x: Math.max(box.x - 4, 0), y: Math.max(box.y - 4, 0), width: box.width + 8, height: Math.min(box.height + 8, max) } });
  await page.setViewportSize({ width: W, height: 800 });
  console.log("wrote", name);
};
const step = async (name, fn) => {
  try { await fn(); } catch (e) { failed.push(name); console.error("FAILED", name, String(e).split("\n")[0]); }
};
const go = async (link) => { await nav.getByRole("link", { name: link, exact: true }).click(); await settle(); };
const signIn = async (user) => {
  await ctx.clearCookies();
  await page.goto("/");
  await page.getByLabel("Username").fill(user);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await nav.waitFor();
  await settle();
};
const close = async () => { await page.keyboard.press("Escape"); await page.waitForTimeout(300); };

// ---- getting started
await step("sign-in", async () => { await ctx.clearCookies(); await page.goto("/"); await page.getByLabel("Username").waitFor(); await shot("sign-in", 640); });

// ---- Budget Manager
await signIn("demo-budget");
await step("dashboard", () => shot("dashboard", 1300));
await step("menu", () => part(page.locator("nav[aria-label='Main navigation']"), "menu", 800));
await step("fiscal-years", async () => { await go("Fiscal Years"); await shot("fiscal-years", 560); });
await step("fiscal-year-page", async () => {
  await page.getByRole("link", { name: /^(FY)?\d{4}/ }).first().click(); await shot("fiscal-year-page", 1100);
});
await step("budgets", async () => { await go("Budgets"); await shot("budgets", 1000); });
await step("bank-accounts", async () => { await go("Bank Accounts"); await shot("bank-accounts", 640); });
await step("events", async () => { await go("Events"); await shot("events", 560); });
await step("fundraiser-page", async () => {
  await page.locator("table a, table button").filter({ hasText: /Concert|Mattress|Sale/ }).first().click(); await shot("fundraiser-page", 1100);
});
await step("reports", async () => { await go("Reports"); await shot("reports", 1000); });
await step("notifications", async () => { await page.goto("/notifications"); await shot("notifications", 1000); });   // 2.4.0 (#551): with tasks
await step("my-account", async () => { await page.getByRole("link", { name: "My account" }).click(); await shot("my-account", 900); });

// ---- Register User
await signIn("demo-register");
await step("register", async () => { await go("Register"); await shot("register", 900); });
await step("register-row", async () => {
  await page.getByRole("button", { name: /Details for transaction/ }).nth(2).click();
  await part(page.locator("table.register"), "register-row", 700);
  await page.getByRole("button", { name: /Details for transaction/ }).nth(2).click();
});
await step("new-transaction", async () => {
  await page.getByRole("button", { name: "New transaction" }).click();
  await part(page.getByRole("dialog"), "new-transaction", 1000); await close();
});
await step("register-print", async () => {
  await page.emulateMedia({ media: "print" }); await shot("register-print", 900); await page.emulateMedia({ media: "screen" });
});
await step("entities", async () => { await go("Entities"); await shot("entities", 800); });
await step("payments", async () => { await go("Payments"); await shot("payments", 700); });

// ---- Invoice Manager
await signIn("demo-invoices");
await step("invoices", async () => { await go("Invoices"); await shot("invoices", 900); });
const catalog = page.getByTestId("inv-catalog");
const tab = async (name) => { await catalog.getByRole("tab", { name }).click(); await settle(); };
await step("catalog-products", async () => { await tab("Products"); await part(catalog, "catalog-products", 700); });
await step("catalog-tax-rates", async () => { await tab("Tax rates"); await part(catalog, "catalog-tax-rates", 500); });
await step("catalog-tax-groups", async () => { await tab("Tax groups"); await part(catalog, "catalog-tax-groups", 500); });
await step("tax-group-form", async () => {
  await catalog.getByRole("row", { name: /General merchandise/ }).getByRole("button", { name: "Edit" }).click();
  await part(page.getByRole("dialog"), "tax-group-form", 700); await close();
});
await step("catalog-categories", async () => { await tab("Categories"); await part(catalog, "catalog-categories", 500); });
await step("category-form", async () => {
  await catalog.getByRole("row", { name: /Memberships/ }).getByRole("button", { name: "Edit" }).click();
  await part(page.getByRole("dialog"), "category-form", 800); await close();
});
await step("product-form", async () => {
  await tab("Products"); await catalog.getByRole("button", { name: "New product" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Category (optional)").selectOption({ label: "Memberships" });
  await dlg.getByLabel("Name").fill("Lifetime membership");
  await page.waitForTimeout(400);
  await part(dlg, "product-form", 1100); await close();
});
await step("new-invoice", async () => {
  await page.getByRole("button", { name: "New invoice" }).click();
  await part(page.getByRole("dialog"), "new-invoice", 1000); await close();
});
await step("invoice-page", async () => {
  await page.getByRole("link", { name: /Lakeside|INV-/ }).first().click(); await shot("invoice-page", 1100);
});
await step("entity-tax-exempt", async () => {
  await go("Entities");
  await page.getByRole("row", { name: /Lakeside Middle School PTO/ }).getByRole("button", { name: "Edit" }).click();
  await part(page.getByRole("dialog"), "entity-tax-exempt", 1000); await close();
});

// ---- Administrator
await signIn("demo-admin");
await step("users", async () => { await go("Users"); await shot("users", 640); });
await step("audit-log", async () => { await go("Audit Log"); await shot("audit-log", 800); });
await step("about-general", async () => { await page.goto("/about/general"); await shot("about-general", 1300); });
await step("backups", async () => { await page.goto("/about/backups"); await shot("backups", 1000); });
await step("invoice-setup", async () => { await go("Invoices Setup"); await shot("invoice-setup", 1300); });
await step("check-setup", async () => { await go("Payments Setup"); await shot("check-setup", 900); });

await browser.close();
if (failed.length) { console.error(`${failed.length} screenshot(s) failed: ${failed.join(", ")}`); process.exit(1); }
console.log("done");
