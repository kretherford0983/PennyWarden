// E2E UI verification (AC-INIT-*, AC-UI-THEME-*, AC-FY-VIS-*, AC-SEC-005/011, AC-AUTH-SELF-001, AC-REG-001).
import { spawn } from "node:child_process";
import { createHmac } from "node:crypto";
import { existsSync, mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

/** Escape every regular-expression metacharacter (backslash included) so text is matched literally. */
const reEscape = (t: string) => t.replace(/[\\^$.*+?()[\]{}|]/g, "\\$&");

const PW = "Correct-Horse-9-Battery";
test.describe.configure({ mode: "serial" });

// 1.8.0 (#113): the security questions every E2E user chooses at the first sign-in
const QUESTIONS: [string, string][] = [["What was the name of your first teacher?", "Mrs. Lee"],
  ["What was the name of your first pet?", "Rex"], ["What was the make and model of your first car?", "Blue Civic"]];

async function setupQuestions(page: Page) {
  await expect(page.getByRole("heading", { name: "Choose your security questions" })).toBeVisible();
  for (const [i, [q, a]] of QUESTIONS.entries()) {
    await page.getByLabel(`Security question ${i + 1}`).selectOption({ label: q });
    await page.getByLabel(`Answer ${i + 1}`).fill(a);
  }
  await page.getByRole("button", { name: "Save and continue" }).click();
}

/** After the password (and two-step) step: the security questions on a first sign-in, then the application. */
async function passGates(page: Page) {
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  const q = page.getByRole("heading", { name: "Choose your security questions" });
  // generous: on a slow build machine the first page after sign-in can take more than the default 5 s (1.6.7)
  await expect(nav.or(q)).toBeVisible({ timeout: 20_000 });
  if (await q.isVisible()) await setupQuestions(page);
  await expect(nav).toBeVisible({ timeout: 20_000 });
}

async function login(page: Page, user: string, pw = PW) {
  await page.goto("/");
  await page.getByLabel("Username").fill(user);
  await page.getByLabel("Password").fill(pw);
  await page.getByRole("button", { name: "Sign in" }).click();
  await passGates(page);
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}

// 1.7.1 (#47): every user has a display name - it is what the top bar shows (#46)
const SHOWN: Record<string, string> = { bm1: "Bea Manager", ru1: "Rae Register" };

async function createUser(page: Page, username: string, roleLabel: string) {
  await page.goto("/users");
  await page.getByRole("button", { name: "New user" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Username").fill(username);
  await dlg.getByLabel("Email").fill(`${username}@example.org`);
  await dlg.getByLabel("Display name").fill(SHOWN[username] || `${username} person`);
  await dlg.getByLabel("Initial password").fill(PW);
  // 1.9.0 (#54): on a local install the roles of every domain are offered together; the domain follows the roles
  await dlg.getByLabel(roleLabel, { exact: true }).check();
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("cell", { name: username, exact: true })).toBeVisible();
}

test("AC-INIT-001..007: fresh install wizard bootstraps a working Administrator", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Initialization Wizard" })).toBeVisible();
  await page.getByLabel("Organization / Workspace Name").fill("E2E Org");
  await page.getByLabel("Administrator Username").fill("admin");
  await page.getByLabel("Administrator Email Address").fill("admin@example.org");
  await page.getByLabel("Password", { exact: true }).fill(PW);
  await page.getByLabel("Password Confirmation").fill(PW);
  await page.getByRole("button", { name: "Initialize" }).click();
  await expect(page.getByRole("heading", { name: "Choose your security questions" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/light-security-questions.png", fullPage: true });
  await setupQuestions(page);   // 1.8.0 (#113): the first Administrator chooses the security questions too
  // 1.9.0 (#54): on a local install the first user holds every role - one account runs the organization's books
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.getByRole("link")).toHaveText(["Dashboard", "Fiscal Years", "Budgets", "Bank Accounts", "Register",
    "Entities", "Reports", "Users", "Audit Log", "System/About"]);
  await nav.getByRole("link", { name: "Users" }).click();
  const row = page.getByRole("row", { name: /admin/ });
  await expect(row).toContainText("COMBINED");
  await expect(row).toContainText("admin@example.org");
  await page.screenshot({ path: "e2e-screenshots/light-local-single-user.png", fullPage: true });
  // the rest of this suite exercises separate security domains: the Administrator keeps only the Administrator role
  // (on a local install an Administrator may change their own roles)
  await row.getByRole("button", { name: "Edit" }).click();
  const ed = page.getByRole("dialog", { name: "Edit admin" });
  await expect(ed.getByText("On a local install one person can hold roles of every security domain.")).toBeVisible();
  for (const label of ["Budget Manager", "Register User", "Auditor"]) {
    if (label !== "Auditor") {   // the extra roles go first: each needs its base role
      const extra = label === "Budget Manager" ? /Budget Admin \(/ : /Register Admin \(/;
      await ed.getByLabel(extra).uncheck();
    }
    await ed.getByLabel(label, { exact: true }).uncheck();
  }
  await ed.getByRole("button", { name: "Save" }).click();
  await expect(ed).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
  await expect(nav.getByRole("link")).toHaveText(["Dashboard", "Users", "Audit Log", "System/About"]);
  await expect(page.getByRole("row", { name: /admin/ })).toContainText("ADMINISTRATOR");
  await nav.getByRole("link", { name: "Audit Log" }).click();
  await expect(page.getByText("SYSTEM_INITIALIZED")).toBeVisible();
  await page.goto("/fiscal-years");
  await expect(page.getByText("You are not authorized to view this module.")).toBeVisible();
  await createUser(page, "bm1", "Budget Manager");
  await createUser(page, "ru1", "Register User");
  await logout(page);
  await login(page, "admin");
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
});

test("AC-UI-THEME-001..003: dark mode persists across logout/login", async ({ page }) => {
  await login(page, "bm1");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /Switch to dark mode/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("link", { name: "Fiscal Years" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await logout(page);
  await login(page, "bm1");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).not.toBe("rgb(246, 247, 249)");
});

test("#47 / #46 / #50: display name is required; the top bar shows it without the roles; roles are on My account", async ({ page }) => {
  await login(page, "admin");
  const userName = page.locator("header.topbar .user-name");
  await expect(userName).toHaveText("admin");                       // the first Administrator: the username
  await expect(page.locator("header.topbar")).not.toContainText("Administrator");
  await page.goto("/users");
  await expect(page.getByRole("row", { name: /bm1/ })).toContainText("Bea Manager");
  // new user: no display name, then one that is too short, then a valid one (stored trimmed)
  await page.getByRole("button", { name: "New user" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Username").fill("dana");
  await dlg.getByLabel("Email").fill("dana@example.org");
  await dlg.getByLabel("Initial password").fill(PW);
  await dlg.getByLabel("Budget User", { exact: true }).check();   // 1.9.0 (#54): local - roles only, the domain follows
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg.getByRole("alert")).toContainText("Display name is required.");
  await dlg.getByLabel("Display name").fill("  ab ");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg.getByRole("alert")).toContainText("Display name must be at least 3 characters.");
  await dlg.getByLabel("Display name").fill("   Dana Display  ");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("row", { name: /dana/ })).toContainText("Dana Display");
  // editing: it cannot be removed or shortened
  await page.getByRole("row", { name: /dana/ }).getByRole("button", { name: "Edit" }).click();
  const ed = page.getByRole("dialog");
  await expect(ed.getByLabel("Display name")).toHaveValue("Dana Display");
  await ed.getByLabel("Display name").fill("");
  await ed.getByRole("button", { name: "Save" }).click();
  await expect(ed.getByRole("alert")).toContainText("Display name is required.");
  await ed.getByLabel("Display name").fill("Da");
  await ed.getByRole("button", { name: "Save" }).click();
  await expect(ed.getByRole("alert")).toContainText("Display name must be at least 3 characters.");
  await ed.getByLabel("Display name").fill("Dana D. Display");
  await ed.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("row", { name: /dana/ })).toContainText("Dana D. Display");
  await logout(page);
  // a Budget Manager: the display name instead of the username, and no roles in the top bar
  await login(page, "bm1");
  await expect(userName).toHaveText("Bea Manager");
  const bar = page.locator("header.topbar");
  await expect(bar).not.toContainText("bm1");
  await expect(bar).not.toContainText("Budget Manager");
  await expect(bar.getByRole("link", { name: "My account" })).toBeVisible();
  await expect(bar.getByRole("button", { name: "Sign out" })).toBeVisible();
  await bar.getByRole("link", { name: "My account" }).click();
  const facts = page.getByLabel("Your account");
  await expect(facts).toContainText("bm1");
  await expect(facts).toContainText("bm1@example.org");
  await expect(facts).toContainText("Budget Manager");
  await expect(page.getByText("Signed in as")).toContainText("Bea Manager");
});

test("#68: signing in while the page's first form-token request is still under way works", async ({ page }) => {
  // The sign-in page asks for its form token when it opens and again when Sign in is pressed. Before 1.6.8 two such
  // requests could overlap: each got its own token (neither carried the cookie yet), the browser kept the token of
  // the answer that arrived last as its cookie while the page sent the other one, and the sign-in was refused with
  // "Missing or invalid CSRF token." The two answers are played here exactly as the server gives them to two
  // overlapping requests - a different token each, in the order that used to fail; the sign-in itself goes to the
  // real server, which accepts it only when the cookie and the token sent with the form are the same.
  let requests = 0;
  let releaseFirst!: () => void;
  const firstHeld = new Promise<void>((r) => (releaseFirst = r));
  const answer = (route: import("@playwright/test").Route, token: string) =>
    route.fulfill({
      status: 200, contentType: "application/json", body: JSON.stringify({ csrf_token: token }),
      headers: { "Set-Cookie": `fm_precsrf=${token}; Path=/; SameSite=Strict` },
    });
  await page.route("**/api/auth/csrf", async (route) => {
    requests += 1;
    if (requests === 1) {
      await firstHeld;                       // still under way when Sign in is pressed
      await answer(route, "A".repeat(43));
    } else {
      releaseFirst();                        // old behaviour: a second request - the first answer lands, then this one
      await new Promise((r) => setTimeout(r, 300));
      await answer(route, "B".repeat(43));
    }
  });
  await page.goto("/");
  await page.getByLabel("Username").fill("bm1");
  await page.getByLabel("Password").fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForTimeout(300);
  releaseFirst();
  await passGates(page);
  expect(requests).toBe(1);                  // Sign in waited for the request that was already under way
});

test("AC-FY-VIS-001..007 + AC-BUD: Budget Manager creates Draft FY, budget, institution and account", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fiscal Years" }).click();
  await page.getByRole("button", { name: "New Fiscal Year" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Identifier").fill("2027");
  await dlg.getByLabel("Start date").fill("2026-07-01");
  await dlg.getByLabel("End date").fill("2027-06-30");
  await dlg.getByRole("button", { name: "Create Fiscal Year" }).click();
  await expect(page.getByRole("heading", { name: /FY2027/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /FY2027/ })).toContainText("Draft");
  await page.getByRole("link", { name: "← Fiscal Years" }).click();
  await expect(page.getByRole("link", { name: "FY2027" })).toBeVisible();
  await page.getByRole("link", { name: "Budgets", exact: true }).click();
  await expect(page.getByLabel("Budget Fiscal Year filter")).toContainText("FY2027 — Draft");
  await page.getByRole("button", { name: "New budget" }).click();
  const b = page.getByRole("dialog");
  await expect(b.getByLabel("Create Budget Fiscal Year")).toContainText("FY2027 — Draft");
  await b.getByLabel("Budget code (e.g. 1000)").fill("1000");
  await b.getByLabel("Name").fill("Operations");
  await b.getByLabel("Amount").fill("100000");
  await b.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("row", { name: /1000 Operations/ })).toContainText("Draft (unapproved)");
  // sub-budget + Other recalculation
  await page.getByRole("button", { name: "+ Sub-budget" }).click();
  const c = page.getByRole("dialog");
  await c.getByLabel("Sub-budget code (e.g. 01)").fill("01");
  await c.getByLabel("Name").fill("Travel");
  await c.getByLabel("Amount").fill("25000");
  await c.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("row", { name: /1000-01 Travel/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /1000-00 Other/ })).toContainText("$75,000.00");
  // institution + account
  await page.getByRole("link", { name: "Bank Accounts" }).click();
  await page.getByRole("button", { name: "New bank account" }).click();
  const a = page.getByRole("dialog", { name: "New bank account" });
  await a.getByRole("button", { name: "+ New institution" }).click();
  const fi = page.getByRole("dialog", { name: "New entity" });
  await fi.getByLabel(/Organization Name/).fill("First National");
  await fi.getByRole("button", { name: "Save" }).click();
  await expect(fi).toHaveCount(0);
  await a.getByLabel("Account name").fill("Operating");
  await expect(a.getByRole("combobox", { name: /Financial Institution/ })).toContainText("First National");
  await a.getByLabel("Full account number").fill("123456789012");
  await a.getByLabel("Primary register account").check();
  await a.getByLabel("Opening balance", { exact: true }).fill("5000.00");
  await a.getByRole("button", { name: "Save" }).click();
  const row = page.getByRole("row", { name: /Operating/ });
  await expect(row).toContainText("******9012");
  await expect(row).not.toContainText("123456789012");
  await row.getByRole("button", { name: "Reveal" }).click();
  await expect(row).toContainText("123456789012");
});

test("AC-FY-VIS-006 / AC-REG-001 / AC-SEC-011: Register User allocates to Draft FY; payloads inert", async ({ page }) => {
  await login(page, "ru1");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
  await nav.getByRole("link", { name: "Entities" }).click();
  await page.getByRole("button", { name: "New entity" }).click();
  const e = page.getByRole("dialog");
  const payload = `<img src=x onerror="window.__xss=1">Vendor`;
  await e.getByLabel(/Organization Name/).fill(payload);
  await e.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("cell", { name: payload })).toBeVisible();
  await nav.getByRole("link", { name: "Register" }).click();
  await expect(page.getByLabel("Register bank account")).toContainText("Operating - ******9012");
  await page.getByRole("button", { name: "New transaction" }).click();
  const t = page.getByRole("dialog");
  await t.getByLabel("Transaction date").fill("2026-08-15");
  await t.getByRole("combobox", { name: "Payee (entity)" }).fill("Vendor");
  await page.getByRole("option", { name: /Vendor/ }).click();
  await expect(t.getByRole("combobox", { name: "Payee (entity)" })).toHaveValue(payload);
  await t.getByLabel("Allocation 1 Fiscal Year").selectOption({ label: "FY2027 — Draft" });
  await t.getByLabel("Allocation 1 Budget").selectOption({ label: "1000-01 Travel (remaining $25,000.00)" });
  await t.getByLabel("Allocation 1 Amount").fill("250.00");
  await t.getByRole("button", { name: "Save" }).click();
  const row = page.getByRole("row", { name: /2026-08-15/ });
  await expect(row).toContainText("$250.00");
  await expect(row).toContainText("$4,750.00");
  await row.getByRole("button", { name: /Details/ }).click();
  await expect(page.getByRole("cell", { name: "FY2027", exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();
});

test("AC-AUTH-SELF-001/004: self-service password change", async ({ page }) => {
  await login(page, "ru1");
  await page.getByRole("link", { name: "My account" }).click();
  await page.getByLabel("Current password").fill(PW);
  await page.getByLabel("New password", { exact: true }).fill("Brand-New-Pass-99");
  await page.getByLabel("Confirm new password").fill("Brand-New-Pass-99");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("Password changed.")).toBeVisible();
  await logout(page);
  await page.getByLabel("Username").fill("ru1");
  await page.getByLabel("Password").fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid username or password.")).toBeVisible();
  await login(page, "ru1", "Brand-New-Pass-99");
});

test("AC-FY-004 / AC-REG-015: UI confirmation flows (gap warning, void)", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fiscal Years" }).click();
  await page.getByRole("button", { name: "New Fiscal Year" }).click();
  const dlg = page.getByRole("dialog", { name: "New Fiscal Year" });
  await dlg.getByLabel("Identifier").fill("2029");
  await dlg.getByLabel("Start date").fill("2028-07-01");
  await dlg.getByLabel("End date").fill("2029-06-30");
  await expect(dlg.getByRole("alert").first()).toContainText("WARNING");
  await dlg.getByRole("button", { name: "Create Fiscal Year" }).click();
  const conf = page.getByRole("dialog", { name: "Confirmation required" });
  await expect(conf).toContainText("Uncovered dates");
  await expect(conf.getByRole("button", { name: "Confirm and continue" })).toBeDisabled();
  await conf.getByLabel(/explicitly confirm/).check();
  await conf.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByRole("heading", { name: /FY2029/ })).toBeVisible();
  await logout(page);
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  await page.getByRole("row", { name: /2026-08-15/ }).getByRole("button", { name: /Details/ }).click();
  await page.getByRole("button", { name: "Void…" }).click();
  const v = page.getByRole("dialog", { name: /Void transaction/ });
  await v.getByLabel("Void reason (required)").fill("Entered twice");
  await expect(v.getByRole("button", { name: "Void transaction" })).toBeDisabled();
  await v.getByLabel("Type VOID to confirm").fill("VOID");
  await v.getByRole("button", { name: "Void transaction" }).click();
  const row = page.getByRole("row", { name: /Details for transaction 1/ });
  await expect(row).toContainText("VOID");
  await expect(row).toContainText("$5,000.00");
});

test("1.7.1: what is typed in the bank account form survives while a new institution is still being loaded", async ({ page }) => {
  // After "+ New institution" the form reloads the institution list and then selects the new one. That step used to
  // put back the form as it was when the institution was saved, wiping anything typed in the meantime.
  await login(page, "bm1");
  await page.getByRole("link", { name: "Bank Accounts" }).click();
  await page.getByRole("button", { name: "New bank account" }).click();
  const a = page.getByRole("dialog", { name: "New bank account" });
  await expect(a.getByRole("combobox", { name: /Financial Institution/ })).toContainText("First National");
  let hold = false;
  let release!: () => void;
  const held = new Promise<void>((r) => (release = r));
  await page.route("**/api/entities?financial_institution=true", async (route) => {
    if (hold) await held;
    await route.continue();
  });
  await a.getByRole("button", { name: "+ New institution" }).click();
  const fi = page.getByRole("dialog", { name: "New entity" });
  await fi.getByLabel(/Organization Name/).fill("Second Savings");
  hold = true;                                   // the list reload that follows the save is kept waiting
  await fi.getByRole("button", { name: "Save" }).click();
  await expect(fi).toHaveCount(0);
  await a.getByLabel("Account name").fill("Typed meanwhile");
  await a.getByLabel("Full account number").fill("555000111222");
  release();
  await expect(a.getByRole("combobox", { name: /Financial Institution/ })).toContainText("Second Savings");
  await expect(a.getByRole("combobox", { name: /Financial Institution/ }).locator("option:checked")).toContainText("Second Savings");
  await expect(a.getByLabel("Account name")).toHaveValue("Typed meanwhile");
  await expect(a.getByLabel("Full account number")).toHaveValue("555000111222");
  await a.getByRole("button", { name: "Cancel" }).click();
});

test("AC-UI-THEME-003: core screens render in light and dark (screenshots)", async ({ page }) => {
  await login(page, "bm1");
  for (const theme of ["dark", "light"]) {
    const cur = await page.locator("html").getAttribute("data-theme");
    if (cur !== theme) await page.getByRole("button", { name: /Switch to/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    for (const [path, name] of [["/", "dashboard"], ["/fiscal-years/1", "fy-detail"], ["/budgets", "budgets"], ["/register", "register"], ["/bank-accounts", "bank-accounts"], ["/entities", "entities"], ["/reports", "reports"]]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: `e2e-screenshots/${theme}-${name}.png`, fullPage: true });
    }
  }
});

test("CR-001: correct the date of a zero-dollar VOID record in the UI", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  await page.getByRole("button", { name: "Zero-dollar VOID record" }).click();
  const z = page.getByRole("dialog", { name: /Zero-dollar VOID/ });
  await z.getByLabel("Date").fill("2026-09-01");
  await z.getByLabel("Check #").fill("1001");
  await z.getByLabel("Void reason (required)").fill("Damaged check");
  await z.getByRole("button", { name: "Create VOID record" }).click();
  const row = page.getByRole("row", { name: /2026-09-01/ }).first();
  await row.getByRole("button", { name: /Details/ }).click();
  await page.getByRole("button", { name: "Correct date…" }).click();
  const d = page.getByRole("dialog", { name: /Correct date of VOID/ });
  await d.getByLabel("Transaction date").fill("2026-09-20");
  await d.getByLabel("Reason (optional)").fill("Forgot to set the date");
  await d.getByRole("button", { name: "Save date" }).click();
  await expect(d).toHaveCount(0);
  const fixed = page.getByRole("row", { name: /2026-09-20/ }).first();
  await expect(fixed).toContainText("VOID");
  await expect(fixed).toContainText("1001");
});


// ---------------------------------------------------------------- v1.2 enhancements
async function apiAs(page: Page) {
  const me = await (await page.request.get("/api/auth/me")).json();
  return (url: string, data: any) => page.request.post(url, { headers: { "X-CSRF-Token": me.csrf_token }, data });
}

test("CR-006 / CR-004: searchable entity picker and 'no attachment' checkbox with warning", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  for (const n of ["Alpha Supplies", "Beta Services", "Gamma Bank Interest"]) {
    expect((await post("/api/entities", { entity_type: "ORGANIZATION", organization_name: n, confirmations: ["DUPLICATE_ENTITY"] })).status()).toBe(201);
  }
  await page.getByRole("link", { name: "Register" }).click();
  await page.getByRole("button", { name: "New transaction" }).click();
  const t = page.getByRole("dialog", { name: /New transaction/ });
  await t.getByLabel("Transaction date").fill("2026-10-31");
  const picker = t.getByRole("combobox", { name: "Payee (entity)" });
  await picker.fill("gam");
  const list = page.getByRole("listbox");
  await expect(list.getByRole("option", { name: /Gamma Bank Interest/ })).toBeVisible();
  await expect(list.getByRole("option", { name: /Alpha Supplies/ })).toHaveCount(0);
  await picker.press("ArrowDown");
  await picker.press("Enter");
  await expect(picker).toHaveValue("Gamma Bank Interest");
  await t.getByLabel("Allocation 1 Fiscal Year").selectOption({ label: "FY2027 — Draft" });
  await t.getByLabel("Allocation 1 Budget").selectOption({ label: "1000-01 Travel (remaining $25,000.00)" });
  await t.getByLabel("Allocation 1 Amount").fill("0.87");
  await t.getByLabel("No attachment will be provided").click(); // warning first; box ticks only after confirming
  await expect(t.getByLabel("No attachment will be provided")).not.toBeChecked();
  const warn = page.getByRole("dialog", { name: "No attachment?" });
  await expect(warn).toContainText("should have supporting documentation");
  await warn.getByRole("button", { name: "Mark as no attachment" }).click();
  await expect(t.getByLabel("No attachment will be provided")).toBeChecked();
  await t.getByLabel("Reason no attachment is available (optional)").fill("Monthly bank service fee - auto debit");
  await t.getByRole("button", { name: "Save" }).click();
  const row = page.getByRole("row", { name: /2026-10-31/ }).first();
  await expect(row).toContainText("No attachment");
  await expect(row).toContainText("Gamma Bank Interest");
});

test("CR-003: transfer between two register accounts from the register", async ({ page }) => {
  await login(page, "bm1");
  const bm = await apiAs(page);
  const fi = await (await page.request.get("/api/entities?financial_institution=true")).json();
  expect((await bm("/api/bank-accounts", { account_name: "Savings", financial_institution_entity_id: fi[0].id, account_type: "SAVINGS",
    account_number: "555566667777", opening_balance: "0.00", opening_balance_date: "2026-07-01" })).status()).toBe(201);
  await logout(page);
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  await page.getByRole("button", { name: "Transfer…" }).click();
  const d = page.getByRole("dialog", { name: "Transfer between accounts" });
  await d.getByLabel("To account").selectOption({ label: "Savings - ******7777" });
  await d.getByLabel("Amount").fill("300.00");
  await d.getByLabel("Transaction date").fill("2026-11-01");
  await d.getByLabel("Clear date (blank = uncleared)").fill("2026-11-02");
  const ent = d.getByRole("combobox", { name: "Entity" });
  await ent.fill("beta");
  await page.getByRole("listbox").getByRole("option", { name: /Beta Services/ }).click();
  await expect(ent).toHaveValue("Beta Services");
  await expect(d).toContainText("Transfer to ******7777 for Beta Services");
  await d.getByRole("button", { name: "Record transfer" }).click();
  await expect(d).toHaveCount(0);
  const row = page.getByRole("row", { name: /2026-11-01/ }).first();
  await expect(row).toContainText("Transfer");
  await expect(row).toContainText("Transfer to ******7777 for Beta Services");
  await expect(row).toContainText("$300.00");
  await page.getByLabel("Register bank account").selectOption({ label: "Savings - ******7777" });
  const dep = page.getByRole("row", { name: /2026-11-01/ }).first();
  await expect(dep).toContainText("Transfer from ******9012 for Beta Services");
  await expect(dep).toContainText("$300.00");
});

test("CR-005: per-allocation 'no attachment' flag on a split transaction", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  await page.getByRole("button", { name: "New transaction" }).click();
  const t = page.getByRole("dialog", { name: /New transaction/ });
  await t.getByLabel("Transaction date").fill("2026-11-05");
  await t.getByRole("button", { name: "Split transaction" }).click();
  for (const [i, amt] of [[1, "4.00"], [2, "6.00"]] as const) {
    await t.getByLabel(`Allocation ${i} Fiscal Year`).selectOption({ label: "FY2027 — Draft" });
    const sel = t.getByLabel(`Allocation ${i} Budget`);
    await sel.selectOption((await sel.locator("option", { hasText: "1000-01 Travel" }).getAttribute("value"))!);
    await t.getByLabel(`Allocation ${i} Amount`).fill(amt);
  }
  await t.getByLabel("Allocation 1 no attachment").click();
  const warn = page.getByRole("dialog", { name: "No attachment?" });
  await expect(warn).toContainText("allocation 1 only");
  await warn.getByRole("button", { name: "Mark as no attachment" }).click();
  await expect(t.getByLabel("Allocation 1 no attachment")).toBeChecked();
  await expect(t.getByLabel("Allocation 2 no attachment")).not.toBeChecked();
  await t.getByLabel("Allocation 1 reason (optional)").fill("Split postage - no receipt");
  await t.getByRole("button", { name: "Save" }).click();
  await expect(t).toHaveCount(0);
  const row = page.getByRole("row", { name: /2026-11-05/ }).first();
  await expect(row).toContainText("$10.00");
  // parent has neither an attachment nor the flag and allocation 2 is undocumented -> listed as missing (checked below)
});

test("CR-002 / CR-005: reports page, audit PDF and entity report; documentation review warnings", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Reports" }).click();
  const open = page.getByRole("link", { name: "Open printable PDF" });
  const href = await open.getAttribute("href");
  expect(href).toContain("/api/reports/audit?fiscal_year_id=");
  const pdf = await page.request.get(href!);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await page.getByRole("tab", { name: "Entity activity" }).click();
  await page.getByLabel("Entity report account").selectOption({ label: "Operating - ******9012" });
  await page.getByRole("button", { name: "Run report" }).click();
  await expect(page.getByRole("row", { name: /Gamma Bank Interest/ })).toContainText("$0.87");
  await expect(page.getByRole("row", { name: /Transfers between accounts/ })).toContainText("$300.00");
  await expect(page.getByRole("link", { name: "Download CSV" })).toBeVisible();
  await page.goto("/fiscal-years/1");
  const review = page.getByRole("heading", { name: /Documentation review/ }).locator("..");
  // v1.4 CR-017: a "no attachment" mark WITH a reason counts as documented and is not listed
  await expect(review).not.toContainText("Monthly bank service fee - auto debit");
  const splitRow = review.getByRole("row", { name: /2026-11-05/ });
  await expect(splitRow).toContainText("Missing attachment");
  await expect(splitRow).toContainText("1 of 2 allocations undocumented");
  await expect(page.getByText(/transaction\(s\) have no supporting attachments/)).toBeVisible();
});

// ---------------------------------------------------------------- v1.3 enhancements
const PDF = Buffer.from("%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n");

async function pickTravel(dlg: any, i = 1) {
  await dlg.getByLabel(`Allocation ${i} Fiscal Year`).selectOption({ label: "FY2027 — Draft" });
  const sel = dlg.getByLabel(`Allocation ${i} Budget`);
  await sel.selectOption((await sel.locator("option", { hasText: "1000-01 Travel" }).getAttribute("value"))!);
}

test("CR-011 / CR-010: double-click saves once, files attach in the form, check numbers are unique", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  await page.getByRole("button", { name: "New transaction" }).click();
  const t = page.getByRole("dialog", { name: /New transaction/ });
  await t.getByLabel("Transaction date").fill("2026-11-10");
  await t.getByLabel("Check #").fill("7001");
  await pickTravel(t);
  await t.getByLabel("Allocation 1 Amount").fill("12.34");
  await t.getByLabel("Transaction attachments").setInputFiles({ name: "receipt-7001.pdf", mimeType: "application/pdf", buffer: PDF });
  await expect(t).toContainText("receipt-7001.pdf");
  await t.getByRole("button", { name: "Save" }).dblclick();
  await expect(t).toHaveCount(0);
  await expect(page.getByRole("row", { name: /2026-11-10/ })).toHaveCount(1);
  await expect(page.getByRole("row", { name: /2026-11-10/ })).toContainText("📎1");
  // the same check number cannot be used twice in the account
  await page.getByRole("button", { name: "New transaction" }).click();
  const t2 = page.getByRole("dialog", { name: /New transaction/ });
  await t2.getByLabel("Transaction date").fill("2026-11-11");
  await t2.getByLabel("Check #").fill("7001");
  await pickTravel(t2);
  await t2.getByLabel("Allocation 1 Amount").fill("5.00");
  await t2.getByRole("button", { name: "Save" }).click();
  await expect(t2.getByRole("alert")).toContainText("Check number 7001 is already used");
  await t2.getByRole("button", { name: "Cancel" }).click();
});

test("CR-012: missing checks are listed in the Fiscal Year reviews and can be resolved", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  const opts = await (await page.request.get("/api/budgets/selectable?fiscal_year_id=1&transaction_type=WITHDRAWAL")).json();
  const travel = opts.find((o: any) => o.label === "1000-01 Travel").id;
  expect((await post("/api/transactions", { bank_account_id: 1, transaction_type: "WITHDRAWAL", transaction_date: "2026-11-12",
    check_number: "7003", allocations: [{ budget_id: travel, amount: "3.00" }] })).status()).toBe(201);
  await page.getByRole("link", { name: "Register" }).click();
  await page.getByRole("button", { name: "Fiscal Year reviews" }).click();
  const sec = page.locator(".missing-checks");
  const row = sec.getByRole("row", { name: /^7002/ });
  await expect(row).toContainText("#7001");
  await expect(row).toContainText("#7003");
  await row.getByRole("button", { name: "Enter transaction" }).click();
  const t = page.getByRole("dialog", { name: /New transaction/ });
  await expect(t.getByLabel("Check #")).toHaveValue("7002");
  await t.getByRole("button", { name: "Cancel" }).click();
  await row.getByRole("button", { name: "Confirm not missing…" }).click();
  const d = page.getByRole("dialog", { name: /Confirm check #7002 not missing/ });
  await d.getByLabel("Note (required)").fill("Torn out of the checkbook and destroyed");
  await d.getByRole("button", { name: "Confirm not missing" }).click();
  await expect(d).toHaveCount(0);
  await expect(sec.getByRole("row", { name: /^7002/ })).toHaveCount(0);
});

test("CR-007 / CR-008: Fiscal Year document types, approval rules and the Close report", async ({ page }) => {
  await login(page, "bm1");
  const post = await apiAs(page);
  const r = await post("/api/fiscal-years", { identifier: "2031", start_date: "2030-07-01", end_date: "2031-06-30", confirmations: ["FY_GAP"] });
  expect(r.status()).toBe(201);
  const fy = await r.json();
  await page.goto(`/fiscal-years/${fy.id}`);
  await page.getByRole("button", { name: "Approve…" }).click();
  let dlg = page.getByRole("dialog", { name: /Approve FY2031/ });
  await expect(dlg).toContainText("Attach the Approval document");
  await dlg.getByLabel("I understand approval cannot be reversed.").check();
  await expect(dlg.getByRole("button", { name: "Approve" })).toBeDisabled();
  await dlg.getByRole("button", { name: "Cancel" }).click();
  // "no approval document" needs a strong confirmation
  await page.getByLabel(/No approval document — this organization/).click();
  const mark = page.getByRole("dialog", { name: "No approval document?" });
  await expect(mark).toContainText("The budget approval should be documented.");
  await mark.getByLabel("Reason (optional)").fill("Approved verbally at the annual meeting");
  await mark.getByLabel(/I understand and confirm/).check();
  await mark.getByRole("button", { name: "Mark as no approval document" }).click();
  await expect(page.locator(".fy-docs")).toContainText("Approved verbally at the annual meeting");
  // uploading an approval document removes the mark
  await page.getByLabel(/Add approval document/).setInputFiles({ name: "board-minutes.pdf", mimeType: "application/pdf", buffer: PDF });
  await expect(page.locator(".fy-docs")).toContainText("board-minutes.pdf");
  await expect(page.getByLabel(/No approval document — this organization/)).toHaveCount(0);
  await page.getByRole("button", { name: "Approve…" }).click();
  dlg = page.getByRole("dialog", { name: /Approve FY2031/ });
  await dlg.getByLabel("I understand approval cannot be reversed.").check();
  await dlg.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("heading", { name: /FY2031/, level: 1 })).toContainText("Approved");
  // an "other" document can be re-labelled as the Audit Signoff
  await page.getByLabel(/Add other document/).setInputFiles({ name: "auditor-letter.pdf", mimeType: "application/pdf", buffer: PDF });
  await page.getByLabel("Document type of auditor-letter.pdf").selectOption("AUDIT_SIGNOFF");
  const signoff = page.locator(".fy-docs section.attachments", { has: page.getByRole("heading", { name: /Audit Signoff/ }) });
  await expect(signoff).toContainText("auditor-letter.pdf");
  const readiness = page.locator("section.card", { has: page.getByRole("heading", { name: "Closure readiness" }) });
  await expect(readiness).not.toContainText("An Audit Signoff document is required");
  await page.locator(".fy-docs").evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "e2e-screenshots/light-fy-documents.png" });
  // Close report on the Reports page
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByRole("tab", { name: "Fiscal Year Close" }).click();
  await page.getByLabel("Close report Fiscal Year").selectOption({ label: "FY2031 — Approved" });
  const href = await page.getByRole("link", { name: "Open Close report PDF" }).getAttribute("href");
  expect(href).toContain(`/api/reports/fy-close?fiscal_year_id=${fy.id}`);
  const pdf = await page.request.get(href!);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
});

test("CR-013 / CR-014 / CR-015: fixed navigation, collapsible menu and pinned register header", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  const opts = await (await page.request.get("/api/budgets/selectable?fiscal_year_id=1&transaction_type=WITHDRAWAL")).json();
  const travel = opts.find((o: any) => o.label === "1000-01 Travel").id;
  for (let i = 0; i < 30; i++) {
    const res = await post("/api/transactions", { bank_account_id: 1, transaction_type: "WITHDRAWAL", transaction_date: "2026-12-01",
      allocations: [{ budget_id: travel, amount: `1.${String(i).padStart(2, "0")}`, description: `Scroll ${i}` }] });
    expect(res.status()).toBe(201);
  }
  await page.getByRole("link", { name: "Register" }).click();
  await expect(page.getByRole("row", { name: /Scroll 29/ })).toBeVisible();
  await page.locator("main.content").evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await page.waitForTimeout(200);
  // top bar and navigation did not move; register header and column headings are still on screen
  expect((await page.locator("header.topbar").boundingBox())!.y).toBe(0);
  expect((await page.getByRole("link", { name: "Dashboard" }).boundingBox())!.y).toBeLessThan(150);
  const h1 = (await page.getByRole("heading", { name: "Register", level: 1 }).boundingBox())!;
  expect(h1.y).toBeGreaterThan(40);
  expect(h1.y).toBeLessThan(140);
  await expect(page.getByRole("button", { name: "New transaction" })).toBeInViewport();
  await expect(page.getByText("Current balance")).toBeInViewport();
  await expect(page.getByLabel("Search")).toBeInViewport();
  await expect(page.locator("table.register thead th", { hasText: "Withdrawal" })).toBeInViewport();
  await expect(page.getByRole("row", { name: /Scroll 0\b/ })).not.toBeInViewport();
  await page.screenshot({ path: "e2e-screenshots/light-register-scrolled.png" });
  // collapsible navigation: icons only, current page still highlighted, remembered after reload
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect.poll(async () => (await nav.boundingBox())!.width).toBeLessThan(70);
  await expect(nav.locator(".nav-label").first()).toBeHidden();
  await expect(nav.getByRole("link", { name: "Register" })).toHaveAttribute("aria-current", "page");
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand navigation" })).toBeVisible();
  expect((await page.locator("header.topbar").boundingBox())!.width).toBe(1280);
  await page.screenshot({ path: "e2e-screenshots/light-register-collapsed.png" });
  await page.getByRole("button", { name: "Expand navigation" }).click();
  await expect(nav.getByText("Register", { exact: true })).toBeVisible();
});

test("1.6.7: Clear puts the register filters back to their defaults and keeps the bank account", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  await expect(page.getByRole("row", { name: /Scroll 29/ })).toBeVisible();
  const clear = page.getByRole("button", { name: "Clear", exact: true });
  const fy = page.getByLabel("Register Fiscal Year filter");
  const account = page.getByLabel("Register bank account");
  await expect(clear).toBeDisabled(); // nothing to clear yet
  const defaultFy = await fy.inputValue();
  const chosenAccount = await account.inputValue();
  await page.getByLabel("Search").fill("Scroll 7");
  await page.getByRole("combobox", { name: "Status" }).selectOption("uncleared");
  await page.getByLabel("From").fill("2026-12-01");
  await fy.selectOption("");
  await expect(page.getByRole("row", { name: /Scroll 7/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /Scroll 29/ })).toHaveCount(0);
  await expect(clear).toBeEnabled();
  await clear.click();
  await expect(page.getByLabel("Search")).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "Status" })).toHaveValue("");
  await expect(page.getByLabel("From")).toHaveValue("");
  await expect(fy).toHaveValue(defaultFy);
  await expect(account).toHaveValue(chosenAccount);
  await expect(page.getByRole("row", { name: /Scroll 29/ })).toBeVisible();
  await expect(clear).toBeDisabled();
  await logout(page);
});

test("1.6.7: the register's Attachments filter shows transactions with or without attachments", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  const withoutAny = page.getByRole("row", { name: /Scroll 29/ }); // the "Scroll" transactions have no attachments
  await expect(withoutAny).toBeVisible();
  const att = page.getByRole("combobox", { name: "Attachments" });
  await expect(att).toHaveValue(""); // All
  const all = await page.locator("table.register tbody tr").count();
  await att.selectOption("yes");
  await expect(withoutAny).toHaveCount(0);
  const yes = await page.locator("table.register tbody tr").count();
  await att.selectOption("no");
  await expect(withoutAny).toBeVisible();
  const no = await page.locator("table.register tbody tr").count();
  expect(yes).toBeGreaterThan(0);
  expect(no).toBeGreaterThan(0);
  expect(yes + no).toBe(all);
  await page.screenshot({ path: "e2e-screenshots/light-register-attachments-filter.png" });
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(att).toHaveValue("");
  await logout(page);
});

test("1.6.7: a documentation review item links to its transaction in the Register", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.goto("/fiscal-years/1");
  const review = page.getByRole("heading", { name: /Documentation review/ }).locator("..");
  // the last listed item: far down the register, so the page has to scroll to it
  const link = review.getByRole("link", { name: /^Open transaction \d+ in the Register$/ }).last();
  const id = (await link.textContent())!.trim();
  const account = (await link.getAttribute("href"))!.match(/account=(\d+)/)![1];
  await link.click();
  await expect(page).toHaveURL(new RegExp(`/register\\?account=${account}&txn=${id}$`));
  await expect(page.getByLabel("Register bank account")).toHaveValue(account);
  await expect(page.getByLabel("Register Fiscal Year filter")).toHaveValue(""); // all dates: the item is always listed
  const row = page.locator(`#txn-${id}`);
  await expect(row).toHaveClass(/linked/);
  await expect(row).toBeInViewport();
  await expect(page.getByRole("button", { name: `Details for transaction ${id}`, exact: true })).toHaveAttribute("aria-expanded", "true");
  await page.screenshot({ path: "e2e-screenshots/light-register-linked-transaction.png" });
  await logout(page);
});

test("1.6.7: an Entity's phone number is typed any way and shown as (nnn) nnn-nnnn", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Entities" }).click();
  await page.getByRole("button", { name: "New entity" }).click();
  let dlg = page.getByRole("dialog", { name: "New entity" });
  await dlg.getByLabel(/Organization Name/).fill("Phone Format Co");
  const phone = dlg.getByLabel("Phone");
  // 1.7.1 (#51): Email and Phone are on one line - labels level, boxes level, the hint below the Phone box
  const email = dlg.getByLabel("Email");
  const [eb, pb] = [(await email.boundingBox())!, (await phone.boundingBox())!];
  expect(Math.abs(eb.y - pb.y)).toBeLessThan(1);
  expect(Math.abs(eb.height - pb.height)).toBeLessThan(1);
  const labelY = async (text: string) => (await dlg.locator(".field-label", { hasText: new RegExp(`^${text}$`) }).boundingBox())!.y;
  expect(Math.abs((await labelY("Email")) - (await labelY("Phone")))).toBeLessThan(1);
  const hint = dlg.getByText("Any format, e.g. 555-123-4567.");
  expect((await hint.boundingBox())!.y).toBeGreaterThanOrEqual(pb.y + pb.height);
  await phone.fill("555.123.4567");
  await phone.blur();
  await expect(phone).toHaveValue("(555) 123-4567"); // tidied as soon as the field is left
  await phone.fill("12345");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toContainText("Enter a 10-digit phone number");
  await phone.fill("1 555 123 4567 ext 12");
  await dlg.getByRole("button", { name: "Save" }).click();
  const row = page.getByRole("row", { name: /Phone Format Co/ });
  await expect(row).toContainText("(555) 123-4567 x12");
  await row.getByRole("button", { name: /Edit/ }).click();
  dlg = page.getByRole("dialog", { name: /^Edit ENT-/ });
  await expect(dlg.getByLabel("Phone")).toHaveValue("(555) 123-4567 x12");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(row).toContainText("(555) 123-4567 x12");
  await logout(page);
});

// ---------------------------------------------------------------- v1.4 enhancements
test("CR-022 / CR-021: version in My Account for every user; bank balance total on the dashboard", async ({ page }) => {
  await login(page, "bm1");
  const total = page.getByTestId("bank-total");
  await expect(total).toContainText("Total (all accounts)");
  await expect(total).toContainText("$");
  await page.screenshot({ path: "e2e-screenshots/light-dashboard-v14.png", fullPage: true });
  await page.getByRole("link", { name: "My account" }).click();
  const about = page.getByRole("region", { name: "About" });
  await expect(about.getByTestId("app-version")).toHaveText(/^\d+\.\d+\.\d+$/);
  await expect(about).toContainText(process.env.FM_BUNDLE ? "Build" : "Development build");
  await expect(about).not.toContainText("Bind address");
  await page.screenshot({ path: "e2e-screenshots/light-account-v14.png", fullPage: true });
  await logout(page);
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await expect(page.getByText("Bind address")).toBeVisible();
});

// ---------------------------------------------------------------- v1.4.1
test("CR-016: audit report signature page — wording, saved wordings, signers", async ({ page }) => {
  await login(page, "bm1");
  const post = await apiAs(page);
  for (const n of ["Jane Trustee", "John Trustee"]) {
    expect((await post("/api/entities", { entity_type: "INDIVIDUAL", primary_contact: n, confirmations: ["DUPLICATE_ENTITY"] })).status()).toBe(201);
  }
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByLabel("Include audit review signature page").check();
  await expect(page.getByLabel("Selected wording")).toContainText("We, the undersigned");
  // new wording with an unknown variable is refused before opening the PDF
  await page.getByLabel("New wording…").check();
  await page.getByLabel("Signature page wording").fill("We, the Trustees of {ORG}, approve {YEAR}.");
  await expect(page.getByRole("alert")).toContainText("Unknown variable(s): {YEAR}");
  await page.getByLabel("Signature page wording").fill("We, the Trustees of {ORG}, approve the records for {FY}.");
  await page.getByRole("button", { name: "Save for future use" }).click();
  await expect(page.getByText("Wording saved for future use.")).toBeVisible();
  await expect(page.getByLabel("Selected wording")).toContainText("We, the Trustees of {ORG}");
  // signers
  await page.getByRole("combobox", { name: "Signer 1" }).fill("Jane");
  await page.getByRole("listbox").getByRole("option", { name: /Jane Trustee/ }).click();
  await page.getByLabel("Signer 1 title").fill("Trustee");
  await page.getByRole("button", { name: "+ Add signer" }).click();
  await page.getByRole("combobox", { name: "Signer 2" }).fill("John");
  await page.getByRole("listbox").getByRole("option", { name: /John Trustee/ }).click();
  const href = await page.getByRole("link", { name: "Open printable PDF" }).getAttribute("href");
  expect(href).toContain("signature_page=true");
  expect(href).toContain("signature_template_id=");
  expect(href!.match(/signer_id=/g)!.length).toBe(2);
  const pdf = await page.request.get(href!);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await page.screenshot({ path: "e2e-screenshots/light-reports-signature.png", fullPage: true });
  // delete the saved wording again
  await page.getByRole("button", { name: "Delete saved wording 1" }).click();
  await expect(page.getByRole("button", { name: "Delete saved wording 1" })).toHaveCount(0);
  await expect(page.getByLabel("Default wording")).toBeChecked();
});

test("CR-020: dashboard charts — defaults, choose charts per user, data tables, light and dark", async ({ page }) => {
  await login(page, "bm1");
  const charts = page.getByRole("region", { name: "Charts" });
  await expect(charts.getByTestId("chart-income_pie")).toBeVisible();
  await expect(charts.getByTestId("chart-monthly")).toBeVisible();
  await expect(charts.getByTestId("chart-expense_vs_budget")).toBeVisible();
  await expect(charts.getByTestId("chart-balances")).toHaveCount(0);
  await expect(charts.getByTestId("chart-monthly").locator(".recharts-surface").first()).toBeVisible();
  await charts.getByTestId("chart-income_pie").screenshot({ path: "e2e-screenshots/light-chart-income-pie.png" });
  // choose charts: add bank balances + cumulative net, remove the income pie; saved for this user
  await charts.getByRole("button", { name: "Choose charts" }).click();
  await charts.getByRole("checkbox", { name: "Bank balances (month end)" }).check();
  await charts.getByRole("checkbox", { name: "Cumulative net (income − expenses)" }).check();
  await charts.getByRole("checkbox", { name: "Income by budget" }).uncheck();
  await charts.getByRole("button", { name: "Done" }).click();
  await expect(charts.getByRole("status")).toHaveText("Chart choice saved");
  await expect(charts.getByTestId("chart-balances")).toBeVisible();
  await expect(charts.getByTestId("chart-income_pie")).toHaveCount(0);
  // data table fallback
  const monthly = charts.getByTestId("chart-monthly");
  await monthly.getByText("Show data table").click();
  await expect(monthly.getByRole("table")).toContainText("Expenses");
  await page.screenshot({ path: "e2e-screenshots/light-dashboard-charts.png", fullPage: true });
  await page.reload();
  await expect(page.getByRole("region", { name: "Charts" }).getByTestId("chart-cumulative_net")).toBeVisible();
  await expect(page.getByRole("region", { name: "Charts" }).getByTestId("chart-income_pie")).toHaveCount(0);
  await page.getByRole("button", { name: /Switch to dark mode/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: "e2e-screenshots/dark-dashboard-charts.png", fullPage: true });
  // restore defaults for later tests
  await page.getByRole("button", { name: /Switch to light mode/ }).click();
  await charts.getByRole("button", { name: "Choose charts" }).click();
  for (const n of ["Bank balances (month end)", "Cumulative net (income − expenses)"]) await charts.getByRole("checkbox", { name: n }).uncheck();
  await charts.getByRole("checkbox", { name: "Income by budget" }).check();
  await expect(charts.getByRole("status")).toHaveText("Chart choice saved");
});

// ---- CR-018: TOTP helper (RFC 6238, SHA-1, 30 s) for the E2E tests
function totp(secret: string, offsetSteps = 0): string {
  const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/[\s=]/g, "").toUpperCase()) bits += alpha.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const step = Math.floor(Date.now() / 1000 / 30) + offsetSteps;
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(step));
  const h = createHmac("sha1", key).update(msg).digest();
  const o = h[h.length - 1] & 0xf;
  const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(n % 1_000_000).padStart(6, "0");
}

test("CR-018: two-step verification — setup, recovery codes, sign-in, trusted browser, admin reset", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "My account" }).click();
  const sec = page.getByRole("region", { name: "Two-step verification" });
  await expect(sec).toContainText("Off");
  await sec.getByRole("button", { name: "Set up two-step verification" }).click();
  await expect(sec.getByRole("img", { name: "QR code for your authenticator app" })).toBeVisible();
  const secret = (await sec.getByTestId("mfa-secret").textContent())!.replace(/\s/g, "");
  expect(secret).toMatch(/^[A-Z2-7]{32}$/);
  await sec.getByLabel("Code from the app").fill("000000");
  await sec.getByRole("button", { name: "Turn on two-step verification" }).click();
  await expect(sec.getByRole("alert")).toContainText("does not match");
  await sec.getByLabel("Code from the app").fill(totp(secret));
  await sec.getByRole("button", { name: "Turn on two-step verification" }).click();
  const codes = sec.getByRole("list", { name: "Recovery codes" }).locator("code");
  await expect(codes).toHaveCount(10);
  const recovery = (await codes.first().textContent())!;
  await page.screenshot({ path: "e2e-screenshots/light-mfa-recovery-codes.png", fullPage: true });
  await expect(sec.getByRole("button", { name: "Continue" })).toBeDisabled();
  await sec.getByLabel("I have saved my recovery codes").check();
  await sec.getByRole("button", { name: "Continue" }).click();
  await expect(sec).toContainText("10 of 10 recovery codes unused");
  await logout(page);

  // sign in: password, then the code
  await page.getByLabel("Username").fill("bm1");
  await page.getByLabel("Password").fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Two-step verification" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/light-mfa-verify.png", fullPage: true });
  await page.getByLabel("Authentication code").fill("123456");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("alert")).toContainText("not valid");
  await page.getByLabel("Authentication code").fill(totp(secret, 1));
  await page.getByLabel("Trust this browser for 30 days").check();
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  await logout(page);
  await login(page, "bm1"); // trusted browser: no code asked
  await logout(page);

  // a recovery code works in another browser context
  const ctx2 = await page.context().browser()!.newContext({ baseURL: page.url().split("/").slice(0, 3).join("/") });
  const p2 = await ctx2.newPage();
  await p2.goto("/");
  await p2.getByLabel("Username").fill("bm1");
  await p2.getByLabel("Password").fill(PW);
  await p2.getByRole("button", { name: "Sign in" }).click();
  await p2.getByRole("button", { name: /Use a recovery code/ }).click();
  await p2.getByLabel("Recovery code").fill(recovery);
  await p2.getByRole("button", { name: "Verify" }).click();
  await expect(p2.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  await ctx2.close();

  // administrator resets bm1's two-step verification
  await login(page, "admin");
  await page.getByRole("link", { name: "Users", exact: true }).click();
  const row = page.getByRole("row", { name: /bm1/ });
  await expect(row).toContainText("On");
  await row.getByRole("button", { name: "Reset two-step" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Reason (required)").fill("E2E test");
  await dlg.getByRole("button", { name: "Reset two-step verification" }).click();
  await expect(dlg.getByRole("status")).toContainText("was reset");
  await dlg.getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("row", { name: /bm1/ })).toContainText("Not set up");
  await logout(page);
  await login(page, "bm1"); // local mode: optional again, no code asked (trusted browser was removed too)
});

// ---------------------------------------------------------------- CR-023 / CR-024 / CR-025 backup and restore
const BACKUP_PASS = "e2e backup passphrase 2026";
let backupFile = "";

test("CR-023 / CR-025: Administrator creates an encrypted backup and restores it", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await expect(page.getByRole("heading", { name: "Backup / Restore" })).toBeVisible();
  await page.getByLabel("Backup passphrase").fill(BACKUP_PASS);
  await page.getByLabel("Repeat the passphrase").fill(BACKUP_PASS);
  await page.getByLabel("Your password").fill(PW);
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Create backup" }).click();
  const download = await dl;
  expect(download.suggestedFilename()).toMatch(/^pennywarden-backup-e2e-org-\d{8}-\d{6}\.fmbak$/);
  backupFile = join(mkdtempSync(join(tmpdir(), "fm-bk-")), download.suggestedFilename());
  await download.saveAs(backupFile);
  await expect(page.getByRole("status")).toContainText("Backup ready");
  await page.screenshot({ path: "e2e-screenshots/light-backup.png", fullPage: true });

  // restore it (replaces the current data; everyone is signed out)
  await page.getByRole("tab", { name: "Restore" }).click();
  await page.getByLabel("Backup file (.fmbak)").setInputFiles(backupFile);
  await page.getByLabel("Backup passphrase").fill(BACKUP_PASS);
  await page.getByLabel("Your password").fill(PW);
  await expect(page.getByRole("button", { name: "Restore" })).toBeDisabled();
  await page.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await page.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByRole("status")).toContainText("Restore complete", { timeout: 30_000 });
  await page.screenshot({ path: "e2e-screenshots/light-restore-done.png", fullPage: true });
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({ timeout: 15_000 });
  await login(page, "admin");
  await page.getByRole("link", { name: "Audit Log", exact: true }).click();
  await expect(page.getByText("SYSTEM_RESTORED").first()).toBeVisible();
});

test("CR-024: a new installation is set up from the backup in the initialization wizard", async ({ page }) => {
  expect(backupFile).not.toBe("");
  const port = 8799;
  const bundle = process.env.FM_BUNDLE;
  const dataDir = mkdtempSync(join(tmpdir(), "fm-wiz-"));
  const args = bundle ? ["--no-browser", "--port", String(port), "--data-dir", dataDir]
    : ["-m", "fmpoc", "--no-browser", "--port", String(port), "--data-dir", dataDir];
  const child = spawn(bundle || process.env.FM_PYTHON || "python", args, { cwd: existsSync(join(process.cwd(), "..", "backend")) ? join(process.cwd(), "..", "backend") : join(process.cwd(), "backend"), stdio: "ignore" });
  try {
    const base = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 120; i++) {
      try { if ((await fetch(`${base}/api/health`)).ok) break; } catch { /* starting */ }
      await new Promise((r) => setTimeout(r, 250));
    }
    await page.goto(base + "/");
    await expect(page.getByRole("heading", { name: "Initialization Wizard" })).toBeVisible();
    await page.getByRole("button", { name: "Restore from a backup instead" }).click();
    await page.getByLabel("Backup file (.fmbak)").setInputFiles(backupFile);
    await page.getByLabel("Backup passphrase").fill("not the passphrase");
    await page.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByRole("alert").last()).toContainText("Wrong passphrase", { timeout: 30_000 });
    await page.getByLabel("Backup file (.fmbak)").setInputFiles(backupFile);
    await page.getByLabel("Backup passphrase").fill(BACKUP_PASS);
    await page.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByRole("status")).toContainText("Restore complete", { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("E2E Org")).toBeVisible();
    await page.getByLabel("Username").fill("admin");
    await page.getByLabel("Password").fill(PW);
    await page.getByRole("button", { name: "Sign in" }).click();
    await passGates(page);
  } finally {
    child.kill();
  }
});

// ---------------------------------------------------------------- v1.5.0 UI polish
test("CR-028 / CR-030 / CR-029 / CR-032: account groups, chart columns, signature preview, aligned passphrase fields", async ({ page }) => {
  await login(page, "bm1");
  // CR-030: charts in two independent columns
  const charts = page.getByRole("region", { name: "Charts" });
  await expect(charts.locator(".chart-cols > .chart-col")).toHaveCount(2);
  // CR-028: dashboard groups with subtotals
  await expect(page.getByTestId("bank-group-CHECKING_SAVINGS")).toContainText("Subtotal Checking & Savings");
  await expect(page.getByTestId("bank-total")).toContainText("Total (all accounts)");
  await page.getByRole("link", { name: "Bank Accounts" }).click();
  await expect(page.getByRole("heading", { name: "Checking & Savings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Investments and Other" })).toBeVisible();
  await expect(page.getByTestId("accounts-CHECKING_SAVINGS")).toContainText("Total Checking & Savings");
  await page.screenshot({ path: "e2e-screenshots/light-bank-accounts-groups.png", fullPage: true });
  // CR-029: preview only the signature page
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByLabel("Include audit review signature page").check();
  const preview = page.getByRole("link", { name: "Preview signature page" });
  const href = await preview.getAttribute("href");
  expect(href).toContain("/api/reports/audit/signature-page?");
  const pdf = await page.request.get(href!);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  await logout(page);
  // CR-032: passphrase fields line up
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await expect(page.getByLabel("Fundraiser module")).toBeVisible(); // the modules panel loads above and shifts the page
  const a = await page.getByLabel("Backup passphrase").boundingBox();
  const b = await page.getByLabel("Repeat the passphrase").boundingBox();
  expect(Math.abs(a!.y - b!.y)).toBeLessThan(2);
  expect(Math.abs(a!.height - b!.height)).toBeLessThan(2);
});

// ---------------------------------------------------------------- 1.7.1 #74: bank account order
test("#74: a Budget Manager sets the bank account order with the keyboard; Dashboard and Register follow it", async ({ page }) => {
  await login(page, "bm1");
  const post = await apiAs(page);
  const fi = await (await post("/api/entities", { entity_type: "ORGANIZATION", organization_name: "Order Test Bank",
    is_financial_institution: true, confirmations: ["DUPLICATE_ENTITY"] })).json();
  for (const [name, num] of [["Order A", "741000000001"], ["Order B", "741000000002"]]) {
    const r = await post("/api/bank-accounts", { account_name: name, financial_institution_entity_id: fi.id, account_type: "CHECKING",
      account_number: num, opening_balance: "0.00", opening_balance_date: "2026-01-01" });
    expect(r.status()).toBe(201);
  }
  await page.getByRole("link", { name: "Bank Accounts" }).click();
  const table = page.getByTestId("accounts-CHECKING_SAVINGS");
  const names = async () => (await table.locator("tbody tr td:nth-child(2)").allInnerTexts()).map((t) => t.trim());
  await expect(table).toContainText("Order B");
  let order = await names();
  const n = order.length;
  expect(order.slice(-2)).toEqual(["Order A", "Order B"]);                 // new accounts go to the end of their group
  await expect(page.getByRole("button", { name: "Move Order B down" })).toBeDisabled();
  // keyboard only: focus the button, press Enter; focus stays on it and the new position is announced
  const up = page.getByRole("button", { name: "Move Order B up" });
  await up.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("order-status")).toHaveText(`Order B moved to position ${n - 1} of ${n} in Checking & Savings.`);
  await expect(page.getByRole("button", { name: "Move Order B up" })).toBeFocused();
  order = await names();
  expect(order.slice(-2)).toEqual(["Order B", "Order A"]);
  await page.keyboard.press("Space");
  await expect(page.getByTestId("order-status")).toHaveText(`Order B moved to position ${n - 2} of ${n} in Checking & Savings.`);
  order = await names();
  expect(order.indexOf("Order B")).toBe(n - 3);
  await page.reload();                                                       // saved
  await expect(table).toContainText("Order B");
  expect(await names()).toEqual(order);
  // the Dashboard lists the group in the same order
  await page.getByRole("link", { name: "Dashboard" }).click();
  const dash = page.getByTestId("bank-group-CHECKING_SAVINGS");
  await expect(dash).toContainText("Order B");
  const dashText = await dash.innerText();
  expect(dashText.indexOf("Order B")).toBeLessThan(dashText.indexOf("Order A"));
  // the Register lists the accounts in that order and still opens on the Primary account
  const accounts = await (await page.request.get("/api/bank-accounts")).json();
  const primary = accounts.find((a: any) => a.is_primary);
  await page.getByRole("link", { name: "Register" }).click();
  const sel = page.getByLabel("Register bank account");
  if (primary) await expect(sel).toHaveValue(String(primary.id));
  const opts = await sel.locator("option").allInnerTexts();
  const want = accounts.filter((a: any) => a.register_enabled).map((a: any) => a.label + (a.status === "CLOSED" ? " (closed)" : ""));
  expect(opts.map((o) => o.trim())).toEqual(want);
  expect(opts.findIndex((o) => o.startsWith("Order B"))).toBeLessThan(opts.findIndex((o) => o.startsWith("Order A")));
  await logout(page);
  // other roles see the order but cannot change it
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Bank Accounts" }).click();
  await expect(page.getByTestId("accounts-CHECKING_SAVINGS")).toContainText("Order B");
  await expect(page.getByRole("button", { name: /^Move / })).toHaveCount(0);
  const me = await (await page.request.get("/api/auth/me")).json();
  const r = await page.request.post(`/api/bank-accounts/${accounts.find((a: any) => a.account_name === "Order A").id}/move`,
    { headers: { "X-CSRF-Token": me.csrf_token }, data: { direction: "up" } });
  expect(r.status()).toBe(403);
});

// ---------------------------------------------------------------- 1.7.2 #55 follow-up
test("1.7.2: an Administrator cannot disable their own account", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "Users", exact: true }).click();
  await page.getByRole("row", { name: /^admin\b/ }).getByRole("button", { name: "Edit" }).click();
  const dlg = page.getByRole("dialog", { name: "Edit admin" });
  await expect(dlg.getByLabel("Active")).toBeDisabled();
  await expect(dlg).toContainText("You cannot disable your own account.");
  await dlg.getByRole("button", { name: "Cancel" }).click();
  // another user's Active box stays available
  await page.getByRole("row", { name: /^bm1\b/ }).getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("dialog", { name: "Edit bm1" }).getByLabel("Active")).toBeEnabled();
});

// ---------------------------------------------------------------- 1.7.2 #56/#57: Current and Available balances
test("#56 / #57: the Register shows Opening, Current (bank) and Available; the bank reconciliation opens", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  const tiles = page.getByTestId("register-balances");
  await expect(tiles.getByTestId("tile-opening")).toContainText("Opening balance");
  await expect(tiles.getByTestId("tile-current")).toContainText("Current balance");
  await expect(tiles.getByTestId("tile-available")).toContainText("Available balance");
  await expect(tiles.getByTestId("tile-ending")).toHaveCount(0);              // open Fiscal Year: no Ending tile
  // the Register's Current balance is the one on the Bank Accounts page
  const sel = page.getByLabel("Register bank account");
  const id = await sel.inputValue();
  const reg = await (await page.request.get(`/api/register?bank_account_id=${id}`)).json();
  const acct = await (await page.request.get(`/api/bank-accounts/${id}`)).json();
  expect(reg.current_balance).toBe(acct.current_balance);
  // an uncleared transaction moves Available, not Current
  const me = await (await page.request.get("/api/auth/me")).json();
  const fy = await (await page.request.get(`/api/fiscal-years/natural?date=${new Date().toISOString().slice(0, 10)}`)).json();
  const opts = await (await page.request.get(`/api/budgets/selectable?fiscal_year_id=${fy.default_fiscal_year_id}&transaction_type=DEPOSIT`)).json();
  const body: any = { bank_account_id: Number(id), transaction_type: "DEPOSIT", no_attachment: true, no_attachment_reason: "e2e",
    allocations: [{ budget_id: opts[0].id, amount: "12.34" }] };
  let r = await page.request.post("/api/transactions", { headers: { "X-CSRF-Token": me.csrf_token }, data: body });
  if (r.status() === 409) {   // confirm whatever the server asks to confirm (e.g. a possible duplicate)
    body.confirmations = ((await r.json()).error.warnings || []).map((w: any) => w.code);
    r = await page.request.post("/api/transactions", { headers: { "X-CSRF-Token": me.csrf_token }, data: body });
  }
  expect(r.status(), await r.text()).toBe(201);
  await page.reload();
  const after = await (await page.request.get(`/api/register?bank_account_id=${id}`)).json();
  expect(after.current_balance).toBe(reg.current_balance);
  expect(Math.round(Number(after.available_balance) * 100)).toBe(Math.round(Number(reg.available_balance) * 100) + 1234);
  await expect(tiles.getByTestId("tile-available")).toContainText(after.available_balance.replace(/^-/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ","));
  // Opening balance: bank balance and outstanding items in a dialog
  const link = tiles.getByRole("button", { name: /Opening balance: bank balance/ });
  if (await link.count()) {
    await link.click();
    const dlg = page.getByRole("dialog", { name: /Opening balance — bank reconciliation/ });
    await expect(dlg.getByTestId("recon-table")).toContainText("Bank balance at the end of");
    await page.screenshot({ path: "e2e-screenshots/light-register-reconciliation.png" });
    await dlg.getByRole("button", { name: "Close" }).last().click();
  }
  // a clear date before the transaction date is refused
  const bad = await page.request.post("/api/transactions", { headers: { "X-CSRF-Token": me.csrf_token }, data: {
    bank_account_id: Number(id), transaction_type: "DEPOSIT", transaction_date: "2026-08-10", clear_date: "2026-08-09",
    allocations: [{ budget_id: opts[0].id, amount: "1.00" }] } });
  expect(bad.status()).toBe(422);
  await page.screenshot({ path: "e2e-screenshots/light-register-balances.png" });
});

// ---------------------------------------------------------------- 1.7.3 #104/#105: Budget filter and Budgets links
test("#104 / #105: a budget on the Budgets page opens the Register filtered to it; the filter survives an account change", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Budgets", exact: true }).click();
  const link = page.getByRole("link", { name: /^1000 .*: show its transactions in the Register$/ }).first();
  await expect(link).toBeVisible();
  const fySel = await page.locator("select").first().inputValue().catch(() => "");
  await link.click();
  await expect(page).toHaveURL(/\/register\?budget=\d+&fiscal_year=\d+/);
  const budgetSel = page.getByLabel("Register Budget filter");
  await expect(budgetSel).not.toHaveValue("");
  await expect(budgetSel.locator("option:checked")).toHaveText(/ - 1000 - /);
  const fyFilter = page.getByLabel("Register Fiscal Year filter");
  if (fySel) await expect(fyFilter).toHaveValue(fySel);
  // every listed transaction has the budget (the API agrees with the page)
  const bid = await budgetSel.inputValue();
  const acct = await page.getByLabel("Register bank account").inputValue();
  const reg = await (await page.request.get(`/api/register?bank_account_id=${acct}&budget_id=${bid}&fiscal_year_id=${await fyFilter.inputValue()}`)).json();
  await expect(page.locator("table.register tbody tr[id^='txn-']")).toHaveCount(reg.transactions.length);
  // changing the account keeps the Budget filter
  const accts = page.getByLabel("Register bank account").locator("option");
  if (await accts.count() > 1) {
    const other = await accts.nth(1).getAttribute("value");
    await page.getByLabel("Register bank account").selectOption(other!);
    await expect(budgetSel).toHaveValue(bid);
  }
  await page.screenshot({ path: "e2e-screenshots/light-register-budget-filter.png" });
  // Clear removes it
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(budgetSel).toHaveValue("");
});

// ---------------------------------------------------------------- 1.7.3 #52/#53: Budget Admin and Register Admin
test("#52 / #53: a Budget Admin deletes a draft budget and a Register Admin deletes an uncleared transaction", async ({ page }) => {
  await login(page, "admin");
  const adm = await apiAs(page);
  for (const [u, roles] of [["ba1", ["BUDGET_MANAGER", "BUDGET_ADMIN"]], ["ra1", ["REGISTER_USER", "REGISTER_ADMIN"]]] as const) {
    const r = await adm("/api/users", { username: u, email: `${u}@example.org`, display_name: `${u} person`, password: PW,
      security_domain: "FINANCIAL", roles });
    expect(r.status(), await r.text()).toBe(201);
  }
  // the extra role needs its base role
  const bad = await adm("/api/users", { username: "ba2", email: "ba2@example.org", display_name: "ba2 person", password: PW,
    security_domain: "FINANCIAL", roles: ["BUDGET_ADMIN"] });
  expect(bad.status()).toBe(422);
  await logout(page);

  // Budget Admin: delete a budget of the draft Fiscal Year
  await login(page, "ba1");
  const post = await apiAs(page);
  const fys = await (await page.request.get("/api/fiscal-years")).json();
  const draft = fys.find((f: any) => f.status === "DRAFT");
  const b = await (await post("/api/budgets", { fiscal_year_id: draft.id, code: "7700", name: "Copied by mistake", budget_type: "EXPENSE", amount: "10.00" })).json();
  await page.goto(`/budgets?fiscal_year_id=${draft.id}`);
  await page.getByRole("button", { name: "Edit 7700" }).click();
  await page.getByRole("button", { name: "Delete budget…" }).click();
  const dlg = page.getByRole("dialog", { name: "Delete 7700 Copied by mistake" });
  await expect(dlg).toContainText("The budget will be deleted.");
  await expect(dlg.getByRole("button", { name: "Delete budget" })).toBeDisabled();
  await dlg.getByLabel("Reason (required)").fill("Copied by mistake");
  await dlg.getByRole("button", { name: "Delete budget" }).click();
  await expect(page.getByRole("button", { name: "Edit 7700" })).toHaveCount(0);
  expect((await page.request.get(`/api/budgets/${b.id}`)).status()).toBe(200);   // still in the database
  await logout(page);

  // Register Admin: delete an uncleared transaction from its edit dialog
  await login(page, "ra1");
  const rpost = await apiAs(page);
  const accts = (await (await page.request.get("/api/bank-accounts")).json()).filter((a: any) => a.register_enabled && a.status === "ACTIVE");
  const nat = await (await page.request.get(`/api/fiscal-years/natural?date=${new Date().toISOString().slice(0, 10)}`)).json();
  const opts = await (await page.request.get(`/api/budgets/selectable?fiscal_year_id=${nat.default_fiscal_year_id}&transaction_type=WITHDRAWAL`)).json();
  const body: any = { bank_account_id: accts[0].id, transaction_type: "WITHDRAWAL", no_attachment: true, no_attachment_reason: "e2e",
    notes: "entered twice", allocations: [{ budget_id: opts[0].id, amount: "3.21", description: "Duplicate entry" }] };
  let r = await rpost("/api/transactions", body);
  if (r.status() === 409) { body.confirmations = ((await r.json()).error.warnings || []).map((w: any) => w.code); r = await rpost("/api/transactions", body); }
  expect(r.status(), await r.text()).toBe(201);
  const t = await r.json();
  await page.goto(`/register?account=${accts[0].id}&txn=${t.id}`);
  const row = page.locator(`#txn-${t.id}`);
  await expect(row).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Delete transaction…" }).click();
  const del = page.getByRole("dialog", { name: `Delete transaction #${t.id}` });
  await del.getByLabel("Reason (required)").fill("Entered twice");
  await del.getByRole("button", { name: "Delete transaction" }).click();
  await expect(page.locator(`#txn-${t.id}`)).toHaveCount(0);
  expect((await page.request.get(`/api/transactions/${t.id}`)).status()).toBe(404);   // hidden from Financial users
});

// ---------------------------------------------------------------- 1.7.3 #88: balance history
test("#88: updating a non-register balance keeps a dated history", async ({ page }) => {
  await login(page, "bm1");
  const post = await apiAs(page);
  const fi = await (await post("/api/entities", { entity_type: "ORGANIZATION", organization_name: "History Brokerage",
    is_financial_institution: true, confirmations: ["DUPLICATE_ENTITY"] })).json();
  const r = await post("/api/bank-accounts", { account_name: "Index Fund", financial_institution_entity_id: fi.id, account_type: "INVESTMENT",
    account_number: "880000000088", register_enabled: false, current_balance: "5000.00" });
  expect(r.status(), await r.text()).toBe(201);
  await page.getByRole("link", { name: "Bank Accounts" }).click();
  const table = page.getByTestId("accounts-INVESTMENTS_OTHER");
  const row = table.getByRole("row", { name: /Index Fund/ });
  await row.getByRole("button", { name: "Update balance" }).click();
  const dlg = page.getByRole("dialog", { name: "Update balance: Index Fund" });
  await dlg.getByLabel("Balance", { exact: true }).fill("5150.25");
  const d = new Date(Date.now() - 20 * 86400000).toISOString().slice(0, 10);
  await dlg.getByLabel("As of").fill(d);
  await dlg.getByLabel("Reason").fill("September statement");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toHaveCount(0);
  await expect(row).toContainText("$5,000.00");                        // a back-dated entry does not replace today's
  await row.getByRole("button", { name: "Balance history of Index Fund" }).click();
  const hist = page.getByTestId("balance-history");
  await expect(hist.locator("tbody tr")).toHaveCount(2);
  await expect(hist).toContainText("September statement");
  await expect(hist).toContainText(d);
  await page.screenshot({ path: "e2e-screenshots/light-balance-history.png" });
});

// ---------------------------------------------------------------- 1.8.0 #89: historic budget traceability
test("#89: a copied budget continues its source; Continues can be set; History shows the lineage", async ({ page }) => {
  await login(page, "bm1");
  const post = await apiAs(page);
  const mkFy = async (body: any) => {
    let r = await post("/api/fiscal-years", { confirmations: [], ...body });
    if (r.status() === 409) r = await post("/api/fiscal-years", { ...body, confirmations: ((await r.json()).error.warnings || []).map((w: any) => w.code) });
    expect(r.status(), await r.text()).toBe(201);
    return r.json();
  };
  const a = await mkFy({ identifier: "2040", start_date: "2039-07-01", end_date: "2040-06-30" });
  const src = await (await post("/api/budgets", { fiscal_year_id: a.id, code: "8900", name: "Lineage", budget_type: "EXPENSE", amount: "100.00" })).json();
  await post("/api/budgets", { fiscal_year_id: a.id, code: "8950", name: "Old name", budget_type: "EXPENSE", amount: "50.00" });
  const b = await mkFy({ identifier: "2041", start_date: "2040-07-01", end_date: "2041-06-30", copy_from_fiscal_year_id: a.id, copy_budget_ids: [src.id] });
  // a new budget in FY2041 picks the FY2040 budget it continues
  await page.goto(`/budgets?fiscal_year_id=${b.id}`);
  await page.getByRole("button", { name: "New budget" }).click();
  const dlg = page.getByRole("dialog", { name: "New budget" });
  await dlg.getByLabel("Budget code (e.g. 1000)").fill("8960");
  await dlg.getByLabel("Name").fill("New name");
  await dlg.getByLabel("Amount").fill("60.00");
  const cont = dlg.getByLabel("Continues budget");
  await expect(cont.locator("option", { hasText: "FY2040 - 8950 - Old name" })).toHaveCount(1);
  await expect(cont.locator("option", { hasText: "8900" })).toHaveCount(0);            // already continued by the copy
  await cont.selectOption({ label: "FY2040 - 8950 - Old name" });
  await dlg.getByRole("button", { name: "Create" }).click();
  await expect(dlg).toHaveCount(0);
  // History of the copied budget
  await page.getByRole("button", { name: "History of 8900" }).click();
  const h = page.getByRole("dialog", { name: "History of 8900 Lineage" });
  await expect(h.getByRole("table", { name: "Budget history" }).locator("tbody tr")).toHaveCount(2);
  await expect(h.locator("tbody tr").first()).toContainText("FY2040");
  await expect(h.locator("tr[aria-current='true']")).toContainText("FY2041");
  await page.screenshot({ path: "e2e-screenshots/light-budget-history.png" });
  await h.locator(".actions").getByRole("button", { name: "Close" }).click();
  await page.getByRole("button", { name: "History of 8960" }).click();
  await expect(page.getByRole("dialog", { name: "History of 8960 New name" })).toContainText("Old name");
});

// ---------------------------------------------------------------- v1.5.0 CR-031: dashboard layout
test("CR-031: dashboard sections can be hidden, reordered and reset; saved per user", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  const order = () => page.locator(".dash-section").evaluateAll((els) => els.map((e) => e.getAttribute("data-section")).filter((k) => k !== "notifications")); // v1.6.3: Notifications is first
  // wait until the dashboard data has loaded (the sections render after /api/dashboard answers)
  await expect(page.locator(".dash-section")).toHaveCount(6);
  expect(await order()).toEqual(["fiscal_year", "budget", "bank", "attention", "charts"]);
  await page.getByRole("button", { name: "Customize dashboard" }).click();
  await expect(page.getByTestId("layout-review")).toHaveCount(0); // Auditors only
  await page.getByRole("button", { name: "Move Bank account balances up" }).click();
  await page.getByRole("button", { name: "Move Bank account balances up" }).click();
  await page.getByTestId("layout-attention").getByRole("checkbox").uncheck();
  await expect(page.getByRole("status").filter({ hasText: "Dashboard layout saved" })).toBeVisible();
  expect(await order()).toEqual(["bank", "fiscal_year", "budget", "charts"]);
  await page.getByRole("button", { name: "Done" }).click();
  await page.reload();
  await expect(page.locator(".dash-section").nth(1)).toHaveAttribute("data-section", "bank");
  expect(await order()).toEqual(["bank", "fiscal_year", "budget", "charts"]);
  await page.screenshot({ path: "e2e-screenshots/light-dashboard-customized.png", fullPage: true });
  await logout(page);
  // another user keeps the default
  await login(page, "bm1");
  await expect(page.locator(".dash-section").nth(1)).toHaveAttribute("data-section", "fiscal_year");
  await logout(page);
  await login(page, "ru1", "Brand-New-Pass-99");
  await expect(page.locator(".dash-section").nth(1)).toHaveAttribute("data-section", "bank");
  await page.getByRole("button", { name: "Customize dashboard" }).click();
  await page.getByRole("button", { name: "Reset to default" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Dashboard layout saved" })).toBeVisible();
  expect(await order()).toEqual(["fiscal_year", "budget", "bank", "attention", "charts"]);
  await expect(page.getByRole("button", { name: "Reset to default" })).toBeDisabled();
  await logout(page);
});

// ---------------------------------------------------------------- v1.6.0 CR-033: fundraisers
test("CR-033: Administrator turns on fundraisers; Budget Manager creates, filters and views one; shells are upcoming", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await page.getByLabel("Fundraiser module").check();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Fundraisers" })).toHaveCount(0);
  await logout(page);

  await login(page, "bm1");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("button", { name: "New fundraiser" }).click();
  let dlg = page.getByRole("dialog", { name: "New fundraiser" });
  await dlg.getByLabel("Name").fill("Harvest Dinner");
  await dlg.getByLabel("Event start date").fill("2026-10-15");
  const exp = dlg.getByLabel("Expense budget (FY2027)");
  await exp.selectOption({ label: "1000 Operations" });
  await expect(dlg.getByRole("note").filter({ hasText: "includes all of its sub-budgets" })).toBeVisible();
  const travel = await exp.locator("option", { hasText: "1000-01 Travel" }).getAttribute("value");
  await exp.selectOption(travel!);
  await expect(dlg.getByRole("note").filter({ hasText: "includes all of its sub-budgets" })).toHaveCount(0);
  await expect(dlg.getByTestId("fr-preview")).toContainText("will be included");
  await dlg.getByRole("button", { name: "Create fundraiser" }).click();
  await expect(page.getByRole("heading", { name: /Harvest Dinner/ })).toBeVisible();
  await expect(page.getByTestId("fr-event")).toHaveText("2026-10-15");
  await expect(page.getByRole("row", { name: /FY2027 Expense 1000-01 Travel/ })).toBeVisible();
  // a filter that matches nothing: warning + no lines
  await page.getByRole("button", { name: "Edit" }).click();
  dlg = page.getByRole("dialog", { name: "Edit fundraiser" });
  await dlg.getByLabel("Description filter (optional)").fill("zzz-no-match");
  await expect(dlg.getByText("Filter in use:")).toBeVisible();
  await expect(dlg.getByTestId("fr-preview")).toContainText("0 of");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("[data-code=FILTER]")).toBeVisible();
  await expect(page.getByTestId("fr-totals")).toContainText("$0.00");
  await page.screenshot({ path: "e2e-screenshots/light-fundraiser-detail.png", fullPage: true });
  // a shell for an event beyond every Fiscal Year: no budgets yet, listed as upcoming
  await page.getByRole("link", { name: "← Fundraisers" }).click();
  await page.getByRole("button", { name: "New fundraiser" }).click();
  dlg = page.getByRole("dialog", { name: "New fundraiser" });
  await dlg.getByLabel("Name").fill("Spring Fair 2028");
  await dlg.getByLabel("Event start date").fill("2028-03-04");
  await expect(dlg.getByText("No open Fiscal Year is within 3 months of the event yet")).toBeVisible();
  await dlg.getByRole("button", { name: "Create fundraiser" }).click();
  await expect(page.locator("[data-code=NO_BUDGETS]")).toBeVisible();
  await page.getByRole("link", { name: "← Fundraisers" }).click();
  await expect(page.getByTestId("fundraiser-list")).toContainText("Harvest Dinner");
  await page.getByLabel("Fundraisers Fiscal Year").selectOption({ label: "Upcoming — no Fiscal Year yet" });
  await expect(page.getByTestId("fundraiser-list")).toContainText("Spring Fair 2028");
  await expect(page.getByTestId("fundraiser-list")).not.toContainText("Harvest Dinner");
  await logout(page);

  // viewers see it, without management buttons
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await expect(page.getByRole("button", { name: "New fundraiser" })).toHaveCount(0);
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  await expect(page.getByRole("heading", { name: /Harvest Dinner/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
  await logout(page);
});

// ---------------------------------------------------------------- v1.6.1 CR-034: fundraiser management
test("CR-034: buckets, cash float, exclusion and fundraiser documents", async ({ page }) => {
  // Budget Manager: no filter, the whole Operations budget (so the fundraiser has expense lines)
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  await page.getByRole("button", { name: "Edit" }).click();
  let dlg = page.getByRole("dialog", { name: "Edit fundraiser" });
  await dlg.getByLabel("Description filter (optional)").fill("");
  await dlg.getByLabel("Expense budget (FY2027)").selectOption({ label: "1000 Operations" });
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("fr-lines").getByRole("button", { name: /^Manage line/ }).first()).toBeVisible();
  await logout(page);

  // Register User manages the lines
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  await page.getByRole("button", { name: "New bucket" }).click();
  dlg = page.getByRole("dialog", { name: "New bucket" });
  await dlg.getByLabel("Bucket name").fill("Food sales");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("fr-buckets")).toContainText("Food sales");
  const before = await page.getByTestId("fr-totals").innerText();
  // line 1: everything into the bucket
  await page.getByTestId("fr-lines").getByRole("button", { name: /^Manage line/ }).nth(0).click();
  dlg = page.getByRole("dialog", { name: "Manage transaction line" });
  await dlg.getByRole("button", { name: "All remaining" }).click();
  await expect(dlg.getByTestId("fr-line-remaining")).toContainText("unassigned $0.00");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("fr-lines").locator(".fr-bucket").first()).toContainText("Food sales");
  await expect(page.getByTestId("fr-chart-buckets")).toBeVisible();
  // line 2: cash float out for the whole amount -> not an expense of the fundraiser
  await page.getByTestId("fr-lines").getByRole("button", { name: /^Manage line/ }).nth(1).click();
  dlg = page.getByRole("dialog", { name: "Manage transaction line" });
  await dlg.getByLabel("Cash float out").check();
  await dlg.getByLabel("Cash float amount").fill("1.00");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("fr-adjustments")).toContainText("cash float taken out $1.00");
  expect(await page.getByTestId("fr-totals").innerText()).not.toEqual(before);
  // line 1 again: exclude (needs a reason; clears the bucket)
  await page.getByTestId("fr-lines").getByRole("button", { name: /^Manage line/ }).nth(0).click();
  dlg = page.getByRole("dialog", { name: "Manage transaction line" });
  await dlg.getByLabel("Exclude this line from the fundraiser").check();
  await dlg.getByLabel("Reason for excluding").fill("Not for the dinner");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("fr-lines").locator("tr.fr-excluded")).toContainText("Excluded: Not for the dinner");
  await expect(page.getByTestId("fr-adjustments")).toContainText("1 excluded line");
  // fundraiser document
  await page.locator("section.attachments").filter({ hasText: "Fundraiser documents" }).locator("input[type=file]")
    .setInputFiles({ name: "flyer.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n") });
  await expect(page.getByRole("heading", { name: "Fundraiser documents (1)" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/light-fundraiser-manage.png", fullPage: true });
  await logout(page);

  // a fundraiser in use cannot be deleted
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  await page.getByRole("button", { name: "Delete…" }).click();
  await page.getByRole("dialog", { name: "Delete fundraiser" }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Archive it instead" })).toBeVisible();
  await logout(page);
});

// ---------------------------------------------------------------- v1.6.2 CR-035: fundraiser report
test("CR-035: fundraiser report PDF; Audit and Close reports can include fundraisers", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  const href = await page.getByRole("link", { name: "Report (PDF)" }).getAttribute("href");
  const pdf = await page.request.get(href!);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  await page.getByRole("link", { name: "Reports" }).click();
  await expect(page.getByLabel("Include fundraisers")).toBeChecked();
  const audit = await page.getByRole("link", { name: "Open printable PDF" }).getAttribute("href");
  expect(audit).toContain("include_fundraisers=true");
  const withFr = await page.request.get(audit!);
  expect(withFr.status()).toBe(200);
  await page.getByLabel("Include fundraisers").uncheck();
  const without = await page.getByRole("link", { name: "Open printable PDF" }).getAttribute("href");
  expect(without).not.toContain("include_fundraisers");
  const plain = await page.request.get(without!);
  expect((await withFr.body()).length).toBeGreaterThan((await plain.body()).length);
  await logout(page);
});

// ---------------------------------------------------------------- v1.6.3 CR-036: reminders and notifications
test("CR-036: organization and personal reminders - bell, dashboard, resolve with a note, read-only viewers", async ({ page }) => {
  const now = new Date(); // the server uses its local date
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  await login(page, "bm1");
  await page.getByRole("link", { name: "Notifications" }).click();
  await expect(page.getByText("Nothing needs your attention.")).toBeVisible();
  // organization reminder due today
  await page.getByRole("button", { name: "New reminder" }).click();
  let dlg = page.getByRole("dialog", { name: "New reminder" });
  await dlg.getByRole("combobox").first().selectOption("ORGANIZATION");
  await dlg.getByLabel("Reminder", { exact: true }).fill("File the annual return");
  await dlg.getByLabel("Due date").fill(today);
  await dlg.getByLabel("Link to (optional)").selectOption("FISCAL_YEAR");
  await dlg.getByLabel("Item").selectOption({ index: 1 });
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("reminder")).toContainText("File the annual return");
  await expect(page.getByTestId("bell-count")).toHaveText("1");
  // personal reminder next year: upcoming, editable, not a notification yet
  await page.getByRole("button", { name: "New reminder" }).click();
  dlg = page.getByRole("dialog", { name: "New reminder" });
  await dlg.getByLabel("Reminder", { exact: true }).fill("Renew my token");
  await dlg.getByLabel("Due date").fill(`${Number(today.slice(0, 4)) + 1}-01-15`);
  await dlg.getByRole("button", { name: "Save" }).click();
  await page.getByRole("tab", { name: "Upcoming" }).click();
  await expect(page.getByTestId("reminder")).toContainText("Renew my token");
  await expect(page.getByRole("button", { name: "Edit Renew my token" })).toBeVisible();
  await expect(page.getByTestId("bell-count")).toHaveText("1");
  // dashboard section
  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.locator("[data-section=notifications]")).toContainText("File the annual return");
  await page.screenshot({ path: "e2e-screenshots/light-dashboard-notifications.png" });
  await logout(page);

  // Register User: sees and resolves the organization reminder with a note; not the other user's personal one
  await login(page, "ru1", "Brand-New-Pass-99");
  await expect(page.getByTestId("bell-count")).toHaveText("1");
  await page.getByRole("link", { name: /Notifications/ }).click();
  await expect(page.getByTestId("reminder")).toHaveCount(1);
  await page.getByRole("button", { name: "Resolve File the annual return" }).click();
  dlg = page.getByRole("dialog", { name: "Resolve reminder" });
  await dlg.getByLabel("Note (optional)").fill("Filed online");
  await dlg.getByRole("button", { name: "Mark as resolved" }).click();
  await expect(page.getByText("Nothing needs your attention.")).toBeVisible();
  await expect(page.getByTestId("bell-count")).toHaveCount(0);
  await page.getByRole("tab", { name: "Resolved" }).click();
  await expect(page.getByTestId("reminder")).toContainText("Filed online");
  await page.getByRole("button", { name: "Reopen File the annual return" }).click();
  await expect(page.getByTestId("bell-count")).toHaveText("1");
  await logout(page);
});

// ---------------------------------------------------------------- 1.6.7: recurring organization reminders
test("1.6.7: a recurring organization reminder creates its next occurrence when resolved", async ({ page }) => {
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  await login(page, "bm1");
  await page.getByRole("link", { name: /Notifications/ }).click();
  await page.getByRole("button", { name: "New reminder" }).click();
  let dlg = page.getByRole("dialog", { name: "New reminder" });
  await expect(dlg.getByRole("combobox", { name: "Repeat", exact: true })).toHaveCount(0); // personal reminders do not repeat
  await dlg.getByRole("combobox").first().selectOption("ORGANIZATION");
  await dlg.getByLabel("Reminder", { exact: true }).fill("Reconcile the bank statement");
  await dlg.getByLabel("Due date").fill(today);
  await dlg.getByRole("combobox", { name: "Repeat", exact: true }).selectOption("yes");
  await dlg.getByRole("spinbutton", { name: "Every" }).fill("3");
  await dlg.getByRole("combobox", { name: "Period" }).selectOption("MONTH");
  await page.screenshot({ path: "e2e-screenshots/light-reminder-repeat-dialog.png" });
  await dlg.getByRole("button", { name: "Save" }).click();
  const item = page.getByTestId("reminder").filter({ hasText: "Reconcile the bank statement" });
  await expect(item.getByTestId("reminder-repeat")).toHaveText("Repeats every 3 months");
  // resolving it announces and creates the next one
  await page.getByRole("button", { name: "Resolve Reconcile the bank statement" }).click();
  dlg = page.getByRole("dialog", { name: "Resolve reminder" });
  await expect(dlg).toContainText("The next one will be due");
  await dlg.getByRole("button", { name: "Mark as resolved" }).click();
  await expect(item).toHaveCount(0);
  await page.getByRole("tab", { name: "Upcoming" }).click();
  await expect(item).toHaveCount(1);
  await expect(item.getByTestId("reminder-repeat")).toHaveText("Repeats every 3 months");
  await page.screenshot({ path: "e2e-screenshots/light-reminder-repeat-upcoming.png" });
  // deleting the upcoming occurrence ends the series
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete Reconcile the bank statement" }).click();
  await expect(item).toHaveCount(0);
  await logout(page);
});

// ---------------------------------------------------------------- v1.6.4 CR-037 / CR-038
test("CR-037 / CR-038: cash count sheet PDF; mark a fundraiser as cancelled and reinstate it", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  await page.getByRole("button", { name: "Cash count sheet…" }).click();
  let dlg = page.getByRole("dialog", { name: "Cash count sheet" });
  // 1.6.7: two empty rows by default, "+ Add signature line" offered right away; never a fourth empty row
  await expect(dlg.locator(".sig-signer")).toHaveCount(2);
  await expect(dlg.getByRole("link", { name: "Open sheet (PDF)" })).toHaveAttribute("href", /blank_lines=2$/);
  await dlg.getByRole("button", { name: "+ Add signature line" }).click();
  await expect(dlg.locator(".sig-signer")).toHaveCount(3);
  await expect(dlg.getByRole("button", { name: "+ Add signature line" })).toHaveCount(0);
  const href = await dlg.getByRole("link", { name: "Open sheet (PDF)" }).getAttribute("href");
  expect(href).toMatch(/blank_lines=3$/);
  expect((await page.request.get(href!.replace("blank_lines=3", "blank_lines=4"))).status()).toBe(422);
  await dlg.getByLabel("Add page 2 for more checks").uncheck();   // page 2 (more check lines, for the back) is optional
  await expect(dlg.getByRole("link", { name: "Open sheet (PDF)" })).toHaveAttribute("href", /extra_checks=false&blank_lines=3$/);
  await dlg.getByLabel("Add page 2 for more checks").check();
  const pdf = await page.request.get(href!);
  expect(pdf.status()).toBe(200);
  // 1.6.7: a person's saved position is filled in as the title when they are chosen; it stays editable,
  // and a title typed by hand is not replaced
  const post = await apiAs(page);
  for (const [n, pos] of [["Petra Position", "Treasurer"], ["Quinn Plain", null]]) {
    expect((await post("/api/entities", { entity_type: "INDIVIDUAL", primary_contact: n, position: pos, confirmations: ["DUPLICATE_ENTITY"] })).status()).toBe(201);
  }
  await dlg.getByRole("button", { name: "Close", exact: true }).last().click();
  await page.getByRole("button", { name: "Cash count sheet…" }).click();
  dlg = page.getByRole("dialog", { name: "Cash count sheet" });
  await dlg.getByRole("combobox", { name: "Signer 1" }).fill("Petra");
  await page.getByRole("listbox").getByRole("option", { name: /Petra Position/ }).click();
  await expect(dlg.getByLabel("Signer 1 title")).toHaveValue("Treasurer");
  await dlg.getByLabel("Signer 2 title").fill("Counter");
  await dlg.getByRole("combobox", { name: "Signer 2" }).fill("Quinn");
  await page.getByRole("listbox").getByRole("option", { name: /Quinn Plain/ }).click();
  await expect(dlg.getByLabel("Signer 2 title")).toHaveValue("Counter");
  await expect(dlg.getByRole("link", { name: "Open sheet (PDF)" })).toHaveAttribute("href", /signer_title=Treasurer.*signer_title=Counter&blank_lines=0$/);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  await dlg.getByRole("button", { name: "Close", exact: true }).last().click();
  await page.getByRole("button", { name: "Mark as cancelled…" }).click();
  dlg = page.getByRole("dialog", { name: "Mark fundraiser as cancelled" });
  await dlg.getByLabel("Reason").fill("Hall double-booked");
  await dlg.getByRole("button", { name: "Mark as cancelled" }).click();
  await expect(page.getByTestId("fr-cancelled")).toContainText("Hall double-booked");
  await expect(page.getByRole("heading", { name: /Harvest Dinner/ })).toContainText("Cancelled");
  await expect(page.getByTestId("fr-lines")).toBeVisible(); // transactions still listed
  await page.getByRole("link", { name: "← Fundraisers" }).click();
  await expect(page.getByRole("row", { name: /Harvest Dinner/ })).toContainText("Cancelled");
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  await page.getByRole("button", { name: "Reinstate" }).click();
  await expect(page.getByTestId("fr-cancelled")).toHaveCount(0);
  await logout(page);
});

// ---------------------------------------------------------------- v1.5.0: license (AGPL-3.0) and source link
test("v1.5.0: sign-in page and My Account offer the source code, license and third-party notices", async ({ page }) => {
  await page.goto("/");
  const legal = page.locator(".login-legal");
  await expect(legal.getByRole("link", { name: "Source code" })).toHaveAttribute("href", /github\.com\/kretherford0983\/PennyWarden/);
  const lic = await page.request.get(await legal.getByRole("link", { name: "License" }).getAttribute("href") as string);
  expect(await lic.text()).toContain("GNU AFFERO GENERAL PUBLIC LICENSE");
  const notices = await page.request.get(await legal.getByRole("link", { name: "Third-party notices" }).getAttribute("href") as string);
  expect(await notices.text()).toContain("recharts");
  await login(page, "bm1");
  await page.getByRole("link", { name: "My account" }).click();
  await expect(page.getByTestId("app-license")).toContainText("AGPL-3.0");
  await expect(page.getByTestId("app-license").getByRole("link", { name: "Source code" })).toBeVisible();
  await logout(page);
});

// ---------------------------------------------------------------- 1.6.6: PennyWarden name and icon
test("1.6.6: the page carries the PennyWarden name and the coin icon (browser tab, sign-in page, top bar)", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("PennyWarden");
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "/favicon.svg");
  const svg = await page.request.get("/favicon.svg");
  expect(svg.status()).toBe(200);
  expect(svg.headers()["content-type"]).toContain("image/svg+xml");
  expect((await page.request.get("/favicon-32.png")).headers()["content-type"]).toContain("image/png");
  expect((await page.request.get("/apple-touch-icon.png")).status()).toBe(200);
  await expect(page.locator(".login-legal")).toContainText("PennyWarden");
  await expect(page.locator(".login-legal img.logo")).toHaveJSProperty("complete", true);
  expect(await page.locator(".login-legal img.logo").evaluate((i) => (i as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await login(page, "bm1");
  await expect(page.locator("header.topbar .brand")).toContainText("PennyWarden");
  expect(await page.locator("header.topbar img.logo").evaluate((i) => (i as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await logout(page);
});

// ---------------------------------------------------------------- v1.5.0: sign-in from a bookmarked page (server mode)
test("v1.5.0: a bookmarked page leads to the dashboard address, two-step setup/verify, then the dashboard", async ({ page }) => {
  const port = 8800;
  const bundle = process.env.FM_BUNDLE;
  const dataDir = mkdtempSync(join(tmpdir(), "fm-srv-"));
  const args = ["--mode", "server", "--host", "127.0.0.1", "--no-browser", "--port", String(port), "--data-dir", dataDir];
  const child = spawn(bundle || process.env.FM_PYTHON || "python", bundle ? args : ["-m", "fmpoc", ...args],
    { cwd: existsSync(join(process.cwd(), "..", "backend")) ? join(process.cwd(), "..", "backend") : join(process.cwd(), "backend"), stdio: "ignore" });
  try {
    const base = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 120; i++) {
      try { if ((await fetch(`${base}/api/health`)).ok) break; } catch { /* starting */ }
      await new Promise((r) => setTimeout(r, 250));
    }
    // initialize from a deep link
    // HF-001: E2E_THROTTLE=6 slows the browser CPU like a busy CI runner (reproduced the sign-in CSRF race)
    if (process.env.E2E_THROTTLE) {
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("Emulation.setCPUThrottlingRate", { rate: Number(process.env.E2E_THROTTLE) });
    }
    await page.goto(base + "/about");
    await page.getByLabel("Organization / Workspace Name").fill("Server Org");
    await page.getByLabel("Administrator Username").fill("admin");
    await page.getByLabel("Administrator Email Address").fill("admin@example.org");
    await page.getByLabel("Password", { exact: true }).fill(PW);
    await page.getByLabel("Password Confirmation").fill(PW);
    await page.getByRole("button", { name: "Initialize" }).click();
    await expect(page.getByRole("heading", { name: "Set up two-step verification" })).toBeVisible();
    await expect(page).toHaveURL(base + "/");
    const secret = (await page.getByTestId("mfa-secret").textContent())!.replace(/\s/g, "");
    await page.getByLabel("Code from the app").fill(totp(secret));
    await page.getByRole("button", { name: "Turn on two-step verification" }).click();
    await page.getByLabel("I have saved my recovery codes").check();
    await page.getByRole("button", { name: "Continue" }).click();
    await setupQuestions(page);   // 1.8.0 (#113): after two-step, the security questions
    await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();

    // a bookmark into the app: sign-in and the two-step step happen on "/", then the dashboard opens
    await page.goto(base + "/users");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await expect(page).toHaveURL(base + "/");
    await page.getByLabel("Username").fill("admin");
    await page.getByLabel("Password").fill(PW);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Two-step verification" })).toBeVisible();
    await page.getByLabel("Authentication code").fill(totp(secret, 1));
    await page.getByRole("button", { name: "Verify" }).click();
    await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
    await expect(page).toHaveURL(base + "/");

    // a page left open across a server upgrade reloads itself once (no loop)
    let loads = 0;
    page.on("load", () => { loads += 1; });
    await page.route("**/api/**", async (route) => {
      const r = await route.fetch();
      await route.fulfill({ response: r, headers: { ...r.headers(), "x-frontend-build": "index-NEWER.js" } });
    });
    await page.getByRole("link", { name: "Users", exact: true }).click();
    await page.waitForTimeout(2500);
    expect(loads).toBe(1);
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await page.unroute("**/api/**");
    await page.getByRole("link", { name: "Dashboard", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
    await expect.poll(() => page.url()).not.toContain("_b=");  // marker dropped once the builds match again
  } finally {
    child.kill();
  }
});

// ---------------------------------------------------------------- 1.8.0 #106: Financial Flow Report
// (last: its transactions would otherwise become lines of the fundraiser in the CR-034 test)
test("#106: Financial Flow Report - review, exclude a line with a reason, note a line, generate the PDF", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  // yesterday (UTC): on or before the server's own "today" whatever its time zone
  const today = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  const accts = (await (await page.request.get("/api/bank-accounts")).json()).filter((a: any) => a.register_enabled && a.status === "ACTIVE");
  const acct = accts[0];
  const nat = await (await page.request.get(`/api/fiscal-years/natural?date=${today}`)).json();
  const dep = await (await page.request.get(`/api/budgets/selectable?fiscal_year_id=${nat.default_fiscal_year_id}&transaction_type=DEPOSIT`)).json();
  const wd = await (await page.request.get(`/api/budgets/selectable?fiscal_year_id=${nat.default_fiscal_year_id}&transaction_type=WITHDRAWAL`)).json();
  const mk = async (body: any) => {
    body = { bank_account_id: acct.id, transaction_date: today, no_attachment: true, no_attachment_reason: "e2e", ...body };
    let r = await post("/api/transactions", body);
    if (r.status() === 409) { body.confirmations = ((await r.json()).error.warnings || []).map((w: any) => w.code); r = await post("/api/transactions", body); }
    expect(r.status(), await r.text()).toBe(201);
    return r.json();
  };
  await mk({ transaction_type: "DEPOSIT", allocations: [{ budget_id: dep[0].id, amount: "300.00", description: "Flow gift A" },
                                                        { budget_id: dep[0].id, amount: "200.00", description: "Flow gift B" }] });
  await mk({ transaction_type: "WITHDRAWAL", allocations: [{ budget_id: wd[0].id, amount: "80.00", description: "Flow supplies" }] });
  const before = await (await post("/api/reports/financial-flow/review", { title: "x", date_from: today, bank_account_ids: [acct.id] })).json();
  const inc0 = Math.round(Number(before.sections[0].income_total) * 100);
  const exp0 = Math.round(Number(before.sections[0].expense_total) * 100);

  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByRole("tab", { name: "Financial Flow" }).click();
  await page.getByLabel("Title").fill("E2E flow");
  await page.getByLabel("From Date").fill(today);
  const picks = page.locator(".account-picks input[type=checkbox]");
  for (let i = 0; i < await picks.count(); i++) await picks.nth(i).uncheck();
  await page.locator(".account-picks label", { hasText: acct.label }).locator("input").check();
  await page.getByRole("button", { name: "Review transactions" }).click();
  await expect(page.getByRole("heading", { name: /E2E flow — Financial Flow Report · .* – Current/ })).toBeVisible();
  const incTotal = page.getByTestId(`flow-total-${acct.id}-income`);
  await expect(incTotal).toHaveText(`$${(inc0 / 100).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  // unchecking asks for a reason; Cancel keeps the line
  const gift = page.getByRole("checkbox", { name: /Flow gift B/ });
  await expect(gift).toBeChecked();
  await gift.click();                                         // asks first: the line stays checked until a reason is given
  const ask = page.getByRole("dialog", { name: "Exclude this line" });
  await expect(ask.getByRole("button", { name: "Exclude line" })).toBeDisabled();
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(gift).toBeChecked();
  await gift.click();
  // 1.10.0 (#139): typed key by key - every letter must land in the box (the focus used to jump to the dialog)
  const reason = ask.getByLabel("Reason (required)");
  await reason.click();
  await reason.pressSequentially("Entered twice", { delay: 20 });
  await expect(reason).toHaveValue("Entered twice");
  await expect(reason).toBeFocused();
  await ask.getByRole("button", { name: "Exclude line" }).click();
  await expect(gift).not.toBeChecked();
  await expect(incTotal).toHaveText(`$${((inc0 - 20000) / 100).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  const diff = inc0 - 20000 - exp0;
  await expect(page.getByTestId(`flow-diff-${acct.id}`)).toContainText(diff >= 0 ? "+" : "\u2212");
  await page.getByRole("textbox", { name: /Note for .* \$80\.00/ }).first().fill("Paid by check");
  await page.screenshot({ path: "e2e-screenshots/light-flow-review.png" });
  const resp = page.waitForResponse((r) => r.url().endsWith("/api/reports/financial-flow") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Generate PDF" }).click();
  const r = await resp;
  expect(r.status()).toBe(200);
  expect(r.headers()["content-type"]).toBe("application/pdf");
  const sent = r.request().postDataJSON();
  expect(sent.exclusions).toHaveLength(1);
  expect(sent.exclusions[0].reason).toBe("Entered twice");
  expect(sent.line_notes.map((n: any) => n.note)).toEqual(["Paid by check"]);
  await expect(page.getByRole("link", { name: "Download PDF" })).toBeVisible();
  // checking the line again discards its reason
  await gift.check();
  await expect(incTotal).toHaveText(`$${(inc0 / 100).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
});

// ---------------------------------------------------------------- 1.8.0 #113: Forgot password
test("#113: security questions at the first sign-in, Forgot password, notices for the user and the Administrators", async ({ page }) => {
  await login(page, "admin");
  const adm = await apiAs(page);
  const r = await adm("/api/users", { username: "fp1", email: "fp1@example.org", display_name: "Frankie Pass", password: PW,
    security_domain: "FINANCIAL", roles: ["BUDGET_USER"] });
  expect(r.status(), await r.text()).toBe(201);
  await logout(page);
  await login(page, "fp1");                                   // chooses the questions on the way in
  await page.getByRole("link", { name: "My account" }).click();
  await expect(page.getByTestId("my-questions").locator("li")).toHaveCount(3);
  await logout(page);

  await page.getByRole("button", { name: "Forgot password?" }).click();
  await page.getByLabel("Username").fill("fp1");
  await page.getByRole("button", { name: "Continue" }).click();
  const q = (await page.getByTestId("security-question").textContent())!.trim();
  const answer = QUESTIONS.find(([text]) => text === q)![1];
  await page.getByLabel("Your answer").fill(` ${answer.toUpperCase()}! `);   // case, spaces and punctuation do not matter
  await page.getByLabel("New password", { exact: true }).fill("Forgot-Reset-Pass-77");
  await page.getByLabel("Confirm new password").fill("Forgot-Reset-Pass-77");
  await page.screenshot({ path: "e2e-screenshots/light-forgot-password.png", fullPage: true });
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(page.getByRole("status")).toContainText("Your password was changed");
  await page.getByRole("button", { name: "Back to sign in" }).first().click();
  await login(page, "fp1", "Forgot-Reset-Pass-77");
  const notice = page.getByTestId("sign-in-notices");
  await expect(notice).toContainText("Your password was reset on");
  await notice.getByRole("button", { name: "OK" }).click();
  await expect(notice).toHaveCount(0);
  await logout(page);

  await login(page, "admin");
  const admin = page.getByTestId("security-notices");
  await expect(admin).toContainText("Frankie Pass reset their password");
  await page.getByRole("link", { name: "Users", exact: true }).click();
  await expect(page.getByRole("row", { name: /fp1/ })).toContainText("Set");
  await admin.getByRole("button", { name: "Dismiss" }).first().click();
  await expect(page.getByTestId("security-notices")).toHaveCount(0);
});

// ---------------------------------------------------------------- 1.9.0 #62: scheduled automatic backups
test("#62: an Administrator sets up scheduled backups to a folder, tests it and runs one now", async ({ page }) => {
  const folder = mkdtempSync(join(tmpdir(), "pw-e2e-backups-"));
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await page.getByRole("tab", { name: "Scheduled" }).click();
  const card = page.locator("section", { has: page.getByRole("heading", { name: "Scheduled backups" }) });
  await card.getByLabel("Back up automatically").check();
  await card.getByLabel("Time").fill("02:30");
  await card.getByLabel("Backup folder").fill(folder);
  await card.getByRole("button", { name: "Test" }).click();
  await expect(card.getByRole("status")).toContainText("can be written to");
  await card.getByLabel("Daily backups").fill("3");
  await expect(card.getByText("Remember this passphrase.")).toBeVisible();
  await card.getByLabel("Backup passphrase").fill("e2e scheduled passphrase");
  await card.getByLabel("Repeat the passphrase").fill("e2e scheduled passphrase");
  await card.getByLabel("Your password").fill(PW);
  await card.getByRole("button", { name: "Save" }).click();
  await expect(card.getByTestId("next-backup")).toContainText("02:30");
  await card.getByRole("button", { name: "Run now" }).click();
  const hist = card.getByRole("table", { name: "Backup history" });
  await expect(hist.locator("tbody tr").first()).toContainText("Done", { timeout: 30_000 });
  await expect(hist.locator("tbody tr").first()).toContainText("Run now");
  await page.screenshot({ path: "e2e-screenshots/light-scheduled-backups.png", fullPage: true });
  const files = readdirSync(folder).filter((f) => f.endsWith(".fmbak"));
  expect(files).toHaveLength(1);
  expect(files[0]).toMatch(/^pennywarden-backup-e2e-org-\d{8}-\d{6}\.fmbak$/);
});

// ---------------------------------------------------------------- 1.10.0 #58: update notification
test("#58: a newer release shows the gold arrow, the What's new dialog with every newer release, and the banner", async ({ page }) => {
  const { createServer } = await import("node:http");
  await login(page, "admin");
  const cur: string = (await (await page.request.get("/api/system/version")).json()).version;
  const [a, b, c] = cur.split(".").map(Number);
  const next = `${a}.${b + 1}.0`, next2 = `${a}.${b + 1}.1`;
  const rel = (v: string, notes: string) => ({ version: v, tag: `v${v}`, channel: "stable", build: null, date: "2026-11-01",
    url: `https://github.com/kretherford0983/PennyWarden/releases/tag/v${v}`, notes, downloads: [] });
  const feed = { schema: 1, releases: [rel(next2, "- **Fix:** a thing <script>window.pwned=1</script>"), rel(next, "Something new"), rel(cur, "this one")] };
  const srv = createServer((req, res) => {
    res.writeHead(req.url === "/releases.json" ? 200 : 404, { "Content-Type": "application/json" });
    res.end(req.url === "/releases.json" ? JSON.stringify(feed) : "{}");
  });
  await new Promise<void>((r) => srv.listen(8796, "127.0.0.1", () => r()));
  try {
    void c;
    await page.getByRole("link", { name: "System/About" }).click();
    const sec = page.locator("section", { has: page.getByRole("heading", { name: "Update check" }) });
    await expect(sec.getByLabel("Check for new versions of PennyWarden")).toBeChecked();
    // A failed "Check now" request is reported, not swallowed (Copilot review of #149).
    await page.route("**/api/updates/check", (r) => r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Server error" }) }));
    await sec.getByRole("button", { name: "Check now" }).click();
    await expect(sec.getByRole("alert")).toBeVisible();
    await expect(sec.getByRole("button", { name: "Check now" })).toBeEnabled();
    await page.unroute("**/api/updates/check");
    await sec.getByRole("button", { name: "Check now" }).click();
    await expect(sec.getByRole("alert")).toHaveCount(0);
    await expect(sec).toContainText(`${next2} is available`);
    await page.reload();
    const dot = page.getByTestId("update-indicator");
    await expect(dot).toBeVisible();
    await dot.click();
    const dlg = page.getByRole("dialog", { name: `PennyWarden ${next2} is available` });
    const notes = dlg.getByTestId("whats-new");
    await expect(notes.getByRole("heading")).toHaveText([new RegExp(`^${reEscape(next2)}`), new RegExp(`^${reEscape(next)} `)]);
    await expect(notes).toContainText("<script>window.pwned=1</script>");          // shown as text, never run
    await expect(notes.locator("b", { hasText: "Fix:" })).toHaveCount(1);
    expect(await page.evaluate(() => (window as any).pwned)).toBeUndefined();
    await expect(dlg.getByRole("link", { name: "Open the download page" })).toHaveAttribute("target", "_blank");
    await page.screenshot({ path: "e2e-screenshots/light-update-whats-new.png" });
    await dlg.getByRole("button", { name: "Close" }).last().click();
    // local install: the banner is on My account, not on the other pages
    await expect(page.getByTestId("update-banner")).toHaveCount(0);
    await page.getByRole("link", { name: "My account" }).click();
    await expect(page.getByTestId("update-banner")).toContainText(`PennyWarden ${next2} is available`);
    // turned off: no arrow
    await page.getByRole("link", { name: "System/About" }).click();
    await sec.getByLabel("Check for new versions of PennyWarden").uncheck();
    await page.reload();
    await expect(page.getByTestId("update-indicator")).toHaveCount(0);
    await sec.getByLabel("Check for new versions of PennyWarden").check();
  } finally {
    srv.close();
  }
});

// ---------------------------------------------------------------- 2.0.0 build 1: check printing (#156-#162)
/** A small valid PNG (a dark zig-zag on transparent), built here so no real signature is ever used. */
async function samplePng(w = 240, h = 60): Promise<Buffer> {
  const { deflateSync } = await import("node:zlib");
  const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (b: Buffer) => { let c = 0xffffffff; for (const x of b) c = crcTable[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const c = Buffer.alloc(4); c.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, c]);
  };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6;
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let x = 0; x < w; x++) {
    const y = Math.floor(h / 2 + (h / 3) * Math.sin(x / 12));
    const o = y * (w * 4 + 1) + 1 + x * 4;
    raw[o] = 20; raw[o + 1] = 20; raw[o + 2] = 80; raw[o + 3] = 255;
  }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}

test("#156-#162: Administrator sets up check printing; a Register User prints a check, with the number confirmed", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await page.getByLabel("Payments module").check();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.reload();
  await page.getByRole("link", { name: "Payments Setup" }).click();
  await expect(page.getByRole("heading", { name: "Payments Setup", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Create" }).click();
  // the editor opens with the preset, the preview drawn with the sample data
  await expect(page.getByRole("heading", { name: /Check style: 3 per page/ })).toBeVisible();
  await expect(page.getByRole("img", { name: "Check preview drawn to scale" })).toContainText("SAMPLE PAYEE COMPANY INC");
  await expect(page.getByLabel("Pay to x")).toHaveValue("1.275");
  // #174: the default memo shows in the preview as it is typed (sample data)
  await page.getByLabel("Default memo").fill("FBA {BUDGET_CODE}, INVOICE {INVOICE}");
  await expect(page.getByRole("img", { name: "Check preview drawn to scale" })).toContainText("FBA 51, INVOICE 12345");
  await page.getByLabel("Default memo").fill("{BUDGET_CODE}, INVOICE {INVOICE}");
  // one click shows the test print with Print
  await page.getByRole("button", { name: "Test print", exact: true }).click();
  const tp = page.getByRole("dialog", { name: "Test print" });
  await expect(tp.getByRole("button", { name: "Print…" })).toBeVisible();
  await tp.getByRole("button", { name: "Close" }).first().click();
  // sections collapse
  await page.getByRole("button", { name: "Field positions" }).click();
  await expect(page.getByLabel("Pay to x")).toBeHidden();
  await page.getByRole("button", { name: "Field positions" }).click();
  await page.getByLabel("Long text sample").check();
  await expect(page.getByText("Does not fit at the smallest size")).toBeVisible();
  page.once("dialog", (d) => d.accept());   // "Leave without saving your changes?"
  await page.getByRole("button", { name: "Back to check styles" }).click();
  // a signer with a (synthetic) signature image; only a SAMPLE preview is ever shown
  await page.getByRole("button", { name: "Add signer…" }).click();
  const sd = page.getByRole("dialog", { name: "Add signer" });
  await sd.getByLabel(/^Name/).fill("Jordan Sample");
  await sd.getByLabel("Title (optional)").fill("Treasurer");
  await sd.getByLabel(/Signature image/).setInputFiles({ name: "signature.png", mimeType: "image/png", buffer: await samplePng() });
  await sd.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("img", { name: "Sample of Jordan Sample's signature" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/light-check-setup.png", fullPage: true });
  await logout(page);

  // Register User: a withdrawal to a vendor, printed as a check
  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  const ent = await (await post("/api/entities", { entity_type: "ORGANIZATION", organization_name: "Sample Supply Company, Inc", confirmations: ["DUPLICATE_ENTITY"] })).json();
  const opts = await (await page.request.get("/api/budgets/selectable?fiscal_year_id=1&transaction_type=WITHDRAWAL")).json();
  const travel = opts.find((o: any) => o.label === "1000-01 Travel").id;
  const tr = await post("/api/transactions", { bank_account_id: 1, transaction_type: "WITHDRAWAL", transaction_date: "2026-11-20", entity_id: ent.id,
    check_number: "8101", allocations: [{ budget_id: travel, amount: "1234.56", invoice_number: "INV-77", description: "Folding tables" }] });
  expect(tr.status()).toBe(201);
  const t = await tr.json();
  await page.goto(`/register?account=1&txn=${t.id}`);
  const row = page.locator(`#txn-${t.id}`);
  await expect(row).toBeVisible();
  // the linked transaction (?txn=) opens its details by itself once the register has loaded - wait for that
  // rather than clicking "Details", which could close them again on a slow machine
  await expect(row.getByRole("button", { name: `Details for transaction ${t.id}` })).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "Print check…" }).click();
  const dlg = page.getByRole("dialog", { name: `Print check – transaction #${t.id}` });
  await dlg.getByRole("button", { name: "Continue" }).click();      // first print from this account: choose the check style
  const preview = dlg.getByRole("img", { name: "Check preview drawn to scale" });
  await expect(preview).toContainText("SAMPLE SUPPLY COMPANY, INC");
  await expect(preview).toContainText("ONE THOUSAND TWO HUNDRED THIRTY-FOUR AND");
  await expect(preview).toContainText("**1,234.56");
  await expect(preview).toContainText("SIGNATURE ON FILE: JORDAN SAMPLE");
  // memo with autocomplete; an unknown variable blocks printing with a suggestion
  const memo = dlg.getByLabel("Memo");
  await memo.fill("TABLES {dtae}");
  await expect(dlg.getByRole("alert").filter({ hasText: "Did you mean {DATE}?" })).toBeVisible();
  await memo.fill("TABLES, {B");
  await expect(dlg.getByRole("option", { name: /BUDGET_CODE/ })).toBeVisible();
  await dlg.getByRole("option", { name: /BUDGET_CODE/ }).click();
  // typing straight on continues after the inserted variable (the cursor is placed there at once)
  await memo.pressSequentially(", {I");
  await memo.press("Enter");
  await expect(memo).toHaveValue("TABLES, {BUDGET_CODE}, {INVOICE}");
  await expect(preview).toContainText("TABLES, 1000-01, INV-77");
  // the number printed on the loaded check must be typed and match
  const confirm = dlg.getByLabel("Type the number printed on the check that is in the printer");
  await confirm.fill("8102");
  await expect(dlg.getByText("That doesn't match check #8101.")).toBeVisible();
  await expect(dlg.getByRole("button", { name: "Print check" })).toBeDisabled();
  await confirm.fill("8101");
  await page.screenshot({ path: "e2e-screenshots/light-print-check.png" });
  await dlg.getByRole("button", { name: "Print check" }).click();
  // #174: the check opens at once in a viewer with Print (one click), a new-tab link and the download
  const viewer = page.getByRole("dialog", { name: "Check #8101" });
  await expect(viewer.getByRole("button", { name: "Print…" })).toBeVisible();
  expect(await viewer.getByRole("link", { name: "Open in a new tab" }).getAttribute("href")).toMatch(/^blob:/);
  await viewer.getByRole("button", { name: "Close" }).first().click();
  await expect(dlg.getByText("Check #8101 is ready.")).toBeVisible();
  await dlg.getByRole("button", { name: "Yes – done" }).click();
  await expect(row.getByText("Check printed")).toBeVisible();
  // printing again is a reprint: a reason is required
  await page.getByRole("button", { name: "Print check again…" }).click();
  await expect(dlg.getByText("Check #8101 was already printed")).toBeVisible();
  await dlg.getByLabel("Type the number printed on the check that is in the printer").fill("8101");
  await expect(dlg.getByRole("button", { name: "Reprint check" })).toBeDisabled();
  await dlg.getByLabel("Reason for the reprint (required)").fill("printer jam, check undamaged");
  await expect(dlg.getByRole("button", { name: "Reprint check" })).toBeEnabled();
  // a damaged check is marked spoiled instead: the number becomes a zero-dollar VOID record
  await dlg.getByRole("button", { name: "Mark check #8101 spoiled…" }).click();
  const sp = page.getByRole("dialog", { name: "Mark check #8101 spoiled" });
  await sp.getByLabel(/Number of the next check/).fill("8102");
  await sp.getByRole("button", { name: "Mark spoiled" }).click();
  await expect(dlg.getByText("Load check #8102")).toBeVisible();
  await dlg.getByRole("button", { name: "Cancel" }).click();
  await page.reload();
  // the spoiled number is kept as a VOID record (the transaction rows have id="txn-<id>"; detail rows don't)
  await expect(page.locator('tr[id^="txn-"]').filter({ hasText: "8101" }).filter({ hasText: "VOID" })).toHaveCount(1);
  await expect(page.locator(`#txn-${t.id}`)).toContainText("8102");
});

// ---------------------------------------------------------------- 2.0.0 build 2: payments (#164)
test("#164: a Register User enters a two-invoice payment, sees the check amount in words, prints it; Create payment shows a transaction locked", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Payments" }).click();
  await expect(page.getByRole("heading", { name: "Payments", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "New payment" }).click();
  const f = page.getByRole("dialog", { name: /^New payment – / });
  await expect(f.getByLabel("Transaction type")).toHaveCount(0);           // always a withdrawal
  await f.getByLabel("Check date").fill("2026-11-25");
  await f.getByRole("combobox", { name: "Payee (entity)" }).fill("Sample Supply");
  await page.getByRole("option", { name: /Sample Supply Company, Inc/ }).click();
  await f.getByRole("button", { name: "More than one invoice" }).click();
  const travel = await f.getByLabel("Allocation 1 Budget").locator("option", { hasText: "1000-01 Travel" }).first().getAttribute("value");
  for (const [i, inv, desc, amt] of [[1, "INV-81", "Chairs", "100.00"], [2, "INV-82", "Tables", "250.50"]] as const) {
    await f.getByLabel(`Allocation ${i} Budget`).selectOption(travel!);
    await f.getByLabel(`Allocation ${i} Amount`).fill(amt);
    await f.locator(".alloc").nth(i - 1).getByLabel("Invoice #").fill(inv);
    await f.locator(".alloc").nth(i - 1).getByLabel("Description").fill(desc);
  }
  await expect(f.getByTestId("amount-preview")).toContainText("**350.50");
  await expect(f.getByTestId("amount-preview")).toContainText("THREE HUNDRED FIFTY AND 50/100");
  await f.getByLabel("Check #").fill("8201");
  await f.getByRole("button", { name: "Save and print check" }).click();
  // saved through the register; the print screen opens at once with the new transaction
  const dlg = page.getByRole("dialog", { name: /^Print check – transaction #\d+$/ });
  const preview = dlg.getByRole("img", { name: "Check preview drawn to scale" });
  await expect(preview).toContainText("SAMPLE SUPPLY COMPANY, INC");
  await expect(preview).toContainText("THREE HUNDRED FIFTY AND");
  await expect(preview).toContainText("1000-01, INVOICE INV-81 AND OTHERS");   // split: the first invoice + "and others"
  await dlg.getByLabel("Type the number printed on the check that is in the printer").fill("8201");
  await dlg.getByRole("button", { name: "Print check" }).click();
  await page.getByRole("dialog", { name: "Check #8201" }).getByRole("button", { name: "Close" }).first().click();
  await expect(dlg.getByText("Check #8201 is ready.")).toBeVisible();
  await dlg.getByRole("button", { name: "Yes – done" }).click();
  const recent = page.locator("section", { has: page.getByRole("heading", { name: /Recently printed checks/ }) });
  await expect(recent.getByRole("row", { name: /8201/ })).toContainText("$350.50");
  await page.screenshot({ path: "e2e-screenshots/light-payments.png", fullPage: true });
  // the bank account is remembered for the next payment
  await page.reload();
  await expect(page.getByLabel("Pay from bank account")).toHaveValue("1");
  // Create payment from the register: the transaction's details are locked
  await recent.getByRole("link", { name: "Open in register" }).first().click();
  await page.getByRole("link", { name: "Create payment…" }).click();
  await expect(page.getByRole("heading", { name: /^Payment for transaction #\d+$/ })).toBeVisible();
  const locked = page.getByRole("region", { name: "Transaction details (locked)" });
  await expect(locked.getByLabel("Payee")).toBeDisabled();
  await expect(locked.getByLabel("Payee")).toHaveValue("Sample Supply Company, Inc");
  await expect(locked).toContainText("INV-82");
  await expect(locked.getByRole("button", { name: "Print check again…" })).toBeVisible();
});

// ---------------------------------------------------------------- 2.0.0 build 3: cover letters, envelopes (#165, #166)
test("#165-#166: Administrator sets up a cover letter and an envelope; a Register User records a handwritten check and prints both", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "Payments Setup" }).click();
  await page.getByRole("button", { name: "New cover letter" }).click();
  await expect(page.getByRole("heading", { name: "Cover letter: Invoice payment letter" })).toBeVisible();
  await page.getByRole("button", { name: "+ Add line" }).click();
  await page.getByLabel("Letterhead line 2", { exact: true }).fill("100 Example Street, Sampletown");
  await page.getByLabel("Name when there is no signer").fill("Pat Example");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.getByRole("button", { name: "Test print (sample data)" }).click();
  const tp = page.getByRole("dialog", { name: "Test print" });
  await expect(tp.getByRole("button", { name: "Print…" })).toBeVisible();
  await tp.getByRole("button", { name: "Close" }).first().click();
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  await page.getByRole("button", { name: "New #10 envelope" }).click();
  await expect(page.getByRole("heading", { name: "Envelope: #10 envelope" })).toBeVisible();
  // the return address starts as the default letter's letterhead
  await expect(page.getByLabel("Return address line 2", { exact: true })).toHaveValue("100 Example Street, Sampletown");
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  const docs = page.locator("section", { has: page.getByRole("heading", { name: "Cover letters and envelopes" }) });
  await expect(docs.getByRole("row", { name: /Invoice payment letter/ })).toContainText("Default");
  await expect(docs.getByRole("row", { name: /#10 envelope/ })).toContainText("Default");
  await page.screenshot({ path: "e2e-screenshots/light-check-letters.png", fullPage: true });
  await logout(page);

  // Register User: a payment with invoice dates; the check is written by hand
  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  const ents = await (await page.request.get("/api/entities?search=Sample%20Supply")).json();
  const ent = (ents.items || ents).find((e: any) => e.display_name === "Sample Supply Company, Inc");
  const opts = await (await page.request.get("/api/budgets/selectable?fiscal_year_id=1&transaction_type=WITHDRAWAL")).json();
  const travel = opts.find((o: any) => o.label === "1000-01 Travel").id;
  const tr = await post("/api/transactions", { bank_account_id: 1, transaction_type: "WITHDRAWAL", transaction_date: "2026-11-27", entity_id: ent.id,
    allocations: [{ budget_id: travel, amount: "40.00", invoice_number: "INV-91", invoice_date: "2026-11-02", description: "Paper" },
                  { budget_id: travel, amount: "60.25", invoice_number: "INV-92", invoice_date: "2026-11-09", description: "Toner" }] });
  expect(tr.status()).toBe(201);
  const t = await tr.json();
  await page.goto(`/register?account=1&txn=${t.id}`);
  const row = page.locator(`#txn-${t.id}`);
  await expect(row.getByRole("button", { name: `Details for transaction ${t.id}` })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("2026-11-09")).toBeVisible();        // invoice date in the details
  await page.getByRole("button", { name: "Print check…" }).click();
  const dlg = page.getByRole("dialog", { name: `Print check – transaction #${t.id}` });
  await dlg.getByLabel("I'm writing the check by hand").check();
  await dlg.getByLabel("Check number you wrote").fill("8301");
  await dlg.getByLabel("Type the check number again").fill("8310");
  await expect(dlg.getByText("The two numbers don't match.")).toBeVisible();
  await expect(dlg.getByRole("button", { name: "Record check number" })).toBeDisabled();
  await dlg.getByLabel("Type the check number again").fill("8301");
  await dlg.getByRole("button", { name: "Record check number" }).click();
  await expect(dlg.getByText("Check number #8301 is recorded for this payment.")).toBeVisible();
  // the payee has no address: printing asks first
  await dlg.getByRole("button", { name: "Print cover letter" }).click();
  const cf = page.getByRole("dialog", { name: "Confirmation required" });
  await expect(cf).toContainText("The payee has no address");
  await cf.getByLabel("I have reviewed these warnings and explicitly confirm.").check();
  await cf.getByRole("button", { name: "Confirm and continue" }).click();
  const lv = page.getByRole("dialog", { name: "Cover letter" });
  await expect(lv.getByRole("button", { name: "Print…" })).toBeVisible();
  await lv.getByRole("button", { name: "Close" }).first().click();
  await expect(dlg.locator(".badge", { hasText: "Attached" })).toHaveCount(1);
  await dlg.getByRole("button", { name: "Print envelope" }).click();
  await cf.getByLabel("I have reviewed these warnings and explicitly confirm.").check();
  await cf.getByRole("button", { name: "Confirm and continue" }).click();
  await page.getByRole("dialog", { name: "Envelope" }).getByRole("button", { name: "Close" }).first().click();
  await expect(dlg.locator(".badge", { hasText: "Attached" })).toHaveCount(2);
  await page.screenshot({ path: "e2e-screenshots/light-handwritten-check.png" });
  await dlg.getByRole("button", { name: "Close" }).first().click();
  await page.reload();
  await expect(page.locator(`#txn-${t.id}`)).toContainText("8301");
});

// ---------------------------------------------------------------- 2.0.0 build 4: voucher checks, two signatures (#167)
test("#167: Administrator sets up a voucher check with two signature lines; a Register User prints it with two signers", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "Payments Setup" }).click();
  await page.getByLabel("New check style from preset").selectOption({ label: "Voucher - check on top, two stubs" });
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name: /Check style: Voucher/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Stubs (voucher check)" })).toBeVisible();
  await expect(page.getByLabel("Stub 2 copy")).toHaveValue("OFFICE");
  await page.getByLabel("Signature lines").selectOption("2");
  await expect(page.getByLabel("Second signature x")).toBeVisible();
  await expect(page.getByRole("img", { name: "Check preview drawn to scale" })).toContainText("SIGNATURE 2");
  await page.getByRole("button", { name: "Save check style" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.getByRole("button", { name: "Test print", exact: true }).click();
  const tp = page.getByRole("dialog", { name: "Test print" });
  await expect(tp.getByRole("button", { name: "Print…" })).toBeVisible();
  await tp.getByRole("button", { name: "Close" }).first().click();
  await page.getByRole("button", { name: "Back to check styles" }).click();
  await page.getByRole("button", { name: "Add signer…" }).click();
  const sd = page.getByRole("dialog", { name: "Add signer" });
  await sd.getByLabel(/^Name/).fill("Pat Example");
  await sd.getByLabel("Title (optional)").fill("Chair");
  await sd.getByLabel(/Signature image/).setInputFiles({ name: "signature.png", mimeType: "image/png", buffer: await samplePng(220, 70) });
  await sd.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("img", { name: "Sample of Pat Example's signature" })).toBeVisible();
  await logout(page);

  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  const ents = await (await page.request.get("/api/entities?search=Sample%20Supply")).json();
  const ent = (ents.items || ents).find((e: any) => e.display_name === "Sample Supply Company, Inc");
  const opts = await (await page.request.get("/api/budgets/selectable?fiscal_year_id=1&transaction_type=WITHDRAWAL")).json();
  const travel = opts.find((o: any) => o.label === "1000-01 Travel").id;
  const tr = await post("/api/transactions", { bank_account_id: 1, transaction_type: "WITHDRAWAL", transaction_date: "2026-11-30", entity_id: ent.id, check_number: "8401",
    allocations: [{ budget_id: travel, amount: "25.00", invoice_number: "INV-95", description: "Pens" },
                  { budget_id: travel, amount: "30.00", invoice_number: "INV-96", description: "Folders" }] });
  expect(tr.status()).toBe(201);
  const t = await tr.json();
  // this account now uses the voucher stock
  const po = await (await page.request.get(`/api/checks/transactions/${t.id}/options`)).json();
  const voucher = po.styles.find((s: any) => s.name.startsWith("Voucher"));
  expect((await page.request.put("/api/checks/accounts/1", { data: { check_style_id: voucher.id }, headers: { "X-CSRF-Token": (await (await page.request.get("/api/auth/me")).json()).csrf_token } })).status()).toBe(200);
  await page.goto(`/register?account=1&txn=${t.id}`);
  const row = page.locator(`#txn-${t.id}`);
  await expect(row.getByRole("button", { name: `Details for transaction ${t.id}` })).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "Print check…" }).click();
  const dlg = page.getByRole("dialog", { name: `Print check – transaction #${t.id}` });
  await dlg.getByLabel("First signature").selectOption({ label: "Jordan Sample (Treasurer)" });
  await dlg.getByLabel("Second signature").selectOption({ label: "Pat Example (Chair)" });
  const preview = dlg.getByRole("img", { name: "Check preview drawn to scale" });
  await expect(preview).toContainText("SIGNATURE ON FILE: PAT EXAMPLE");
  await expect(preview).toContainText("SIGNATURE ON FILE: JORDAN SAMPLE");
  await expect(dlg.getByText(/The stubs below the check list the 2 lines/)).toBeVisible();
  await dlg.getByLabel("Type the number printed on the check that is in the printer").fill("8401");
  await page.screenshot({ path: "e2e-screenshots/light-voucher-check.png" });
  await dlg.getByRole("button", { name: "Print check" }).click();
  await page.getByRole("dialog", { name: "Check #8401" }).getByRole("button", { name: "Close" }).first().click();
  await expect(dlg.getByText("Check #8401 is ready.")).toBeVisible();
  await dlg.getByRole("button", { name: "Yes – done" }).click();
  await expect(row.getByText("Check printed")).toBeVisible();
});
