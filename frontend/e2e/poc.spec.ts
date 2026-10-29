// E2E UI verification (AC-INIT-*, AC-UI-THEME-*, AC-FY-VIS-*, AC-SEC-005/011, AC-AUTH-SELF-001, AC-REG-001).
import { spawn, spawnSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { existsSync, mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";

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

/** 2.0.0 build 11 (#215): a row action other than Edit is an item of the row's ⋯ menu ("Actions for <row name>"). */
async function rowAction(scope: Page | Locator, rowName: string | RegExp, item: string | RegExp) {
  const page = "page" in scope ? (scope as Locator).page() : (scope as Page);
  await scope.getByRole("button", { name: typeof rowName === "string" ? `Actions for ${rowName}` : new RegExp(`^Actions for ${rowName.source}`) }).first().click();
  await page.getByRole("menu").getByRole("menuitem", { name: item }).click();
}

/** 2.0.0 build 11 (#216): System/About is in tabs; open one (the System/About page must be showing). */
async function aboutTab(page: Page, name: string) {
  await page.getByRole("tablist", { name: "System/About sections" }).getByRole("tab", { name, exact: true }).click();
  await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
}

/** Build 13: the buttons and links that would change something, still shown on these pages (none while maintenance mode
 * is on for a non-Administrator). Returns "path: label" for each. */
const CHANGE_ACTION = /^(New |\+ |Edit|✎|Actions for |Transfer|Zero-dollar|Delete|Close|Make |Update balance|Copy|Reopen|Resolve|Print check|Reprint|Create |Record |Mark |Void|Correct |Upload|Add |Attach|Duplicate|Archive|Cancel fundraiser|Reinstate|Lock|Unlock|Reject|Approve|Save)/;
async function pausedActions(page: Page, paths: string[]): Promise<string[]> {
  const out: string[] = [];
  for (const path of paths) {
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    // (tabs such as "Resolved" switch views; they change nothing)
    for (const el of await page.locator(".content :is(button, a.button):visible:not([role=tab])").all()) {
      const name = ((await el.getAttribute("aria-label")) || (await el.innerText())).trim();
      if (CHANGE_ACTION.test(name) && !(await el.isDisabled())) out.push(`${path}: ${name}`);
    }
  }
  return [...new Set(out)];
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}

// 1.7.1 (#47): every user has a display name - it is what the top bar shows (#46)
const SHOWN: Record<string, string> = { bm1: "Bea Manager", ru1: "Rae Register", auditor1: "Ada Auditor" };

async function createUser(page: Page, username: string, roleLabel: string) {
  await page.goto("/users");
  await page.getByRole("button", { name: "New user" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Username").fill(username);
  await dlg.getByLabel("First name").fill((SHOWN[username] || `${username} person`).split(" ")[0]);   // 2.0.0 (#134)
  await dlg.getByLabel("Last name").fill((SHOWN[username] || `${username} person`).split(" ")[1] || "Person");
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
  await page.getByLabel("Administrator First Name").fill("Pat");
  await page.getByLabel("Administrator Last Name").fill("Example");
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
  const ed = page.getByRole("dialog", { name: "Edit Pat Example - admin" });
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
  await expect(page.locator(".audit-action", { hasText: "Application initialized" })).toBeVisible();   // 2.0.0 (#133)
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
  await dlg.getByLabel("First name").fill("Dana");
  await dlg.getByLabel("Last name").fill("Sample");
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
  await rowAction(page, /1000 Operations/, "+ Sub-budget");
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
  await expect(page.getByRole("cell", { name: payload, exact: true })).toBeVisible();
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

test("#343: a failed sign-in clears and focuses the password; Change password shows the requirements and keeps the fields", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill("ru1");
  await page.getByLabel("Password").fill("Not-The-Password-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid username or password.")).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveValue("");
  await expect(page.getByLabel("Password")).toBeFocused();
  await expect(page.getByLabel("Username")).toHaveValue("ru1");
  await page.getByLabel("Password").fill("Brand-New-Pass-99");
  await page.getByRole("button", { name: "Sign in" }).click();
  await passGates(page);
  await page.getByRole("link", { name: "My account" }).click();
  const list = page.getByTestId("password-checklist");
  const req = (id: string) => list.locator(`li[data-req="${id}"]`);
  // shown before typing, from the server's policy, nothing met yet
  await expect(req("length")).toContainText("At least 12 characters (at most 128)");
  for (const id of ["length", "letter_digit", "not_username", "differs_current", "confirm_matches"])
    await expect(req(id)).toHaveAttribute("data-state", "unmet");
  await expect(req("differs_temporary")).toHaveCount(0);
  await expect(list).toHaveAttribute("aria-live", "polite");
  await page.getByLabel("Current password").fill("Wrong-Current-11");
  const np = page.getByLabel("New password", { exact: true });
  await np.fill("short1");
  await expect(req("letter_digit")).toHaveAttribute("data-state", "met");
  await expect(req("length")).toHaveAttribute("data-state", "unmet");
  await expect(req("length")).toContainText("(not met)");
  await np.fill("Another-Pass-77");
  await expect(req("length")).toHaveAttribute("data-state", "met");
  await expect(req("length")).toContainText("(met)");
  await expect(req("confirm_matches")).toHaveAttribute("data-state", "unmet");
  await page.getByLabel("Confirm new password").fill("Another-Pass-77");
  for (const id of ["length", "letter_digit", "not_username", "differs_current", "confirm_matches"])
    await expect(req(id)).toHaveAttribute("data-state", "met");
  // met is green and unmet red (theme tokens)
  const green = await req("length").evaluate((el) => getComputedStyle(el).color);
  expect(green).not.toBe(await page.getByText("Password requirements").evaluate((el) => getComputedStyle(el).color));
  // a refused change keeps everything that was typed
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("The current password is incorrect.")).toBeVisible();
  await expect(page.getByLabel("Current password")).toHaveValue("Wrong-Current-11");
  await expect(np).toHaveValue("Another-Pass-77");
  await expect(page.getByLabel("Confirm new password")).toHaveValue("Another-Pass-77");
  const card = page.locator("form.card", { has: page.getByRole("heading", { name: "Change password" }) });
  await card.screenshot({ path: "e2e-screenshots/light-change-password-checklist.png" });
  await page.getByRole("button", { name: /Switch to dark mode/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await card.screenshot({ path: "e2e-screenshots/dark-change-password-checklist.png" });
  await page.getByRole("button", { name: /Switch to light mode/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.setViewportSize({ width: 390, height: 844 });
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: "e2e-screenshots/phone-change-password-checklist.png" });
  // on a phone the list goes under the fields
  const fieldsBox = (await card.locator(".pw-fields").boundingBox())!;
  const listBox = (await card.locator(".pw-checklist").boundingBox())!;
  expect(listBox.y).toBeGreaterThanOrEqual(fieldsBox.y + fieldsBox.height - 1);
  await page.setViewportSize({ width: 1280, height: 720 });
  await logout(page);
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

// ---------------------------------------------------------------- 2.3.0 build 9 (#373)
test("#373: the Quarterly / Annual financial report - period choice, commentary, PDF and presentation", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByRole("tab", { name: "Quarterly / Annual" }).click();
  // periods that haven't started are listed but can't be chosen (whatever today is)
  const opts = await page.getByLabel("Period", { exact: true }).locator("option").evaluateAll((os) => os.map((o: any) => ({ v: o.value, d: o.disabled })));
  expect(opts.map((o) => o.v)).toEqual(["Q1", "Q2", "Q3", "Q4", "ANNUAL"]);
  await page.getByLabel("Commentary (optional)").fill("Giving was steady this quarter.");
  const open = page.getByRole("link", { name: "Open report PDF" });
  const href = (await open.getAttribute("href"))!;
  expect(href).toContain("/api/reports/period?");
  expect(href).toContain("commentary=Giving");
  const pdf = await page.request.get(href);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await page.getByLabel("Period", { exact: true }).selectOption("ANNUAL");
  const deck = await page.request.get((await page.getByRole("link", { name: "Download presentation (.pptx)" }).getAttribute("href"))!);
  expect(deck.status()).toBe(200);
  expect(deck.headers()["content-type"]).toContain("presentationml");
  await page.screenshot({ path: "e2e-screenshots/light-period-report.png", fullPage: true });
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

test("1.6.7 / 2.1.0 (#258): the register's Attachments filter - Yes, Missing (the documentation review), Marked", async ({ page }) => {
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
  await att.selectOption("missing");
  await expect(withoutAny).toBeVisible();
  await expect(withoutAny).toContainText("Missing attachment");
  const missing = await page.locator("table.register tbody tr").count();
  expect(yes).toBeGreaterThan(0);
  expect(missing).toBeGreaterThan(0);
  expect(yes + missing).toBeLessThanOrEqual(all); // VOID ones and documented "no attachment" marks are neither
  await page.screenshot({ path: "e2e-screenshots/light-register-attachments-filter.png" });
  await att.selectOption("marked");
  await expect(withoutAny).toHaveCount(0);
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(att).toHaveValue("");
  await logout(page);
});

test("2.1.0 (#262, #260, #259): register sort, electronic payment, reorder attachments", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Register" }).click();
  // #262: sort by Cleared (the balance column becomes the cleared balance), remembered after a reload, then reset
  const cleared = page.getByRole("columnheader", { name: "Cleared", exact: true });
  await expect(cleared).toHaveAttribute("aria-sort", "none");
  await cleared.getByRole("button").click();
  await expect(cleared).toHaveAttribute("aria-sort", "ascending");
  await expect(page.getByRole("columnheader", { name: "Cleared balance" })).toBeVisible();
  // the sort is saved in the background: wait for that save before reloading (CI flake, 2.3.0 build 1)
  const saved = page.waitForResponse((r) => r.url().includes("/api/me/preferences") && r.request().method() === "PUT");
  await cleared.getByRole("button").click();
  await saved;
  await expect(cleared).toHaveAttribute("aria-sort", "descending");
  await page.reload();
  await expect(page.getByRole("columnheader", { name: "Cleared", exact: true })).toHaveAttribute("aria-sort", "descending");
  await page.getByRole("button", { name: "Reset to default" }).click();
  await expect(page.getByRole("columnheader", { name: "Date", exact: true })).toHaveAttribute("aria-sort", "ascending");
  await expect(page.getByRole("columnheader", { name: "Balance", exact: true })).toBeVisible();
  // #260: an electronic payment with a reference
  await page.getByRole("button", { name: "New transaction" }).click();
  const t = page.getByRole("dialog", { name: /New transaction/ });
  await t.getByLabel("Transaction date").fill("2026-11-20");
  await t.getByLabel("Electronic payment (no physical check)").check();
  await expect(t.getByLabel("Check #", { exact: true })).toHaveCount(0);
  await t.getByLabel("Electronic payment method").selectOption("ACH");
  await t.getByLabel("Kind of number").selectOption("reference");
  await t.getByLabel("Payment reference").fill("ACH-20261120-CONF-0048213377");
  // build 2 feedback: the number has the full width of its column, on the row under "Paid by"
  const ref = await t.getByLabel("Payment reference").boundingBox();
  const kind = await t.getByLabel("Kind of number").boundingBox();
  const paid = await t.getByLabel("Electronic payment method").boundingBox();
  expect(ref!.width).toBeGreaterThan(200);
  expect(Math.abs(ref!.y - kind!.y)).toBeLessThan(4);
  expect(ref!.y).toBeGreaterThan(paid!.y + paid!.height);
  await t.screenshot({ path: "e2e-screenshots/light-electronic-payment-form.png" });
  await pickTravel(t);
  await t.getByLabel("Allocation 1 Amount").fill("41.17");
  await t.getByRole("button", { name: "Save" }).click();
  await expect(t).toHaveCount(0);
  const row = page.getByRole("row", { name: /2026-11-20/ });
  await expect(row).toContainText("Electronic");
  await expect(row).toContainText("ACH-20261120-CONF-0048213377");
  await page.getByRole("combobox", { name: "Payment" }).selectOption("electronic");
  await expect(page.locator("table.register tbody tr")).toHaveCount(1);
  await page.screenshot({ path: "e2e-screenshots/light-register-electronic-payment.png" });
  // #259: two attachments, reordered
  await row.getByRole("button", { name: /Details for transaction/ }).click();
  const files = page.locator("section.attachments").filter({ hasText: "Transaction attachments" }).first();
  for (const n of ["first-invoice.pdf", "second-receipt.pdf"]) {
    await files.locator("input[type=file]").setInputFiles({ name: n, mimeType: "application/pdf", buffer: PDF });
    await expect(files).toContainText(n);
  }
  await files.getByRole("button", { name: "Reorder…" }).click();
  const order = page.locator("section.attachments").filter({ hasText: "set the order" });
  await order.getByRole("button", { name: "Move second-receipt.pdf up" }).click();
  await order.getByRole("button", { name: "Save order" }).click();
  await expect(files.locator(".att-list li").first()).toContainText("second-receipt.pdf");
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await logout(page);
});

test("2.1.0 (#257, #261, #283): Budget Review with projection choices; the Planning Sheet from the Fiscal Years page", async ({ page }) => {
  // Budget Managers only: a Register User has no Budget Review tab
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.goto("/reports");
  await expect(page.getByRole("tab", { name: "Financial Flow" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Budget Review" })).toHaveCount(0);
  await logout(page);
  await login(page, "bm1");
  await page.goto("/reports");
  await page.getByRole("tab", { name: "Budget Review" }).click();
  await page.getByLabel("Projected column").check();
  const choices = page.locator("fieldset.projection-choices");
  await expect(choices).toContainText("Projected budgets");
  const first = choices.getByRole("checkbox").first();
  await first.uncheck();
  await choices.getByRole("button", { name: "Save projection choices" }).click();
  await expect(choices.getByRole("status")).toHaveText("Saved.");
  await page.getByLabel("Next year's budget").check();
  await page.getByRole("button", { name: "Run report" }).click();
  const rep = page.locator(".budget-review");
  await expect(rep.getByRole("heading", { name: /Budget Review — / })).toBeVisible();
  await expect(rep).toContainText("Complete: no projection");
  // #283: a block per budget - Budgeted, Actual and Difference rows, an Avg column
  const table = rep.getByRole("table", { name: "Budget Review" });
  await expect(table.getByRole("rowheader", { name: "Budgeted" }).first()).toBeVisible();
  await expect(table.getByRole("rowheader", { name: "Difference" }).first()).toBeVisible();
  await expect(rep.getByRole("link", { name: "Download CSV" })).toHaveAttribute("href", /format=csv/);
  const pdf = await page.request.get((await rep.getByRole("link", { name: "Open PDF" }).getAttribute("href"))!);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  await page.screenshot({ path: "e2e-screenshots/light-budget-review.png", fullPage: true });
  // back to the defaults, so later tests see the usual figures
  await choices.getByRole("button", { name: "Back to defaults" }).click();
  await expect(choices.getByRole("status")).toHaveText("Saved.");
  // #261: the Planning Sheet from the Fiscal Years page (build 3 feedback: no Fiscal Year needs to be opened)
  await page.getByRole("link", { name: "Fiscal Years" }).click();
  await page.getByRole("button", { name: "Planning sheet…" }).click();
  const dlg = page.getByRole("dialog", { name: "Fiscal Year Planning Sheet" });
  await expect(dlg.getByTestId("planning-context")).toContainText("Planning");
  await expect(dlg).toContainText("isn't required for the Fiscal Year closure review");
  const href = await dlg.getByRole("link", { name: "Open planning sheet PDF" }).getAttribute("href");
  const sheet = await page.request.get(href!);
  expect(sheet.status()).toBe(200);
  expect(sheet.headers()["content-type"]).toBe("application/pdf");
  // #283: the Budget Review can follow the sheet in the same PDF
  await dlg.getByLabel(/Include the Budget Review/).check();
  const withReview = await dlg.getByRole("link", { name: "Open planning sheet PDF" }).getAttribute("href");
  expect(withReview).toContain("include_review=true");
  const both = await page.request.get(withReview!);
  expect(both.status()).toBe(200);
  expect((await both.body()).length).toBeGreaterThan((await sheet.body()).length);
  await dlg.getByRole("button", { name: "Done" }).click();
  await expect(dlg).toHaveCount(0);
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
  await expect(page.getByRole("term").filter({ hasText: "Bind address" })).toBeVisible();   // 2.0.0: the settings table lists it too
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
  // 2.3.0 (#371): budget amounts are gross - the ⓘ on the budget chart explains it
  await charts.getByRole("button", { name: "About Expense budgets: budgeted vs spent" }).click();
  await expect(charts.getByRole("note").filter({ hasText: "Budget amounts are gross." })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(charts.getByRole("note").filter({ hasText: "Budget amounts are gross." })).toHaveCount(0);
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

test("#371: budgets are gross - Gross amount on the budget table and form, with the disclaimer line", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Budgets", exact: true }).click();
  await expect(page.getByRole("columnheader", { name: "Gross amount" }).first()).toBeVisible();
  await expect(page.getByTestId("gross-budget-note")).toContainText("Budget amounts are gross. Offsetting income or expense recorded in a budget of the opposite type, such as a reimbursement, is not subtracted.");
  await page.getByRole("button", { name: "New budget" }).click();
  const dlg = page.getByRole("dialog", { name: "New budget" });
  await expect(dlg.getByLabel("Gross amount")).toBeVisible();
  await dlg.getByRole("button", { name: "Cancel" }).click();
  await logout(page);
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
  await rowAction(row, "bm1", "Reset two-step");
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Reason (required)").fill("E2E test");
  await dlg.getByRole("button", { name: "Reset two-step verification" }).click();
  await expect(dlg.getByRole("status")).toContainText("was reset");
  await dlg.getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("row", { name: /bm1/ })).toContainText("Not set up");
  await logout(page);
  await login(page, "bm1"); // local mode: optional again, no code asked (trusted browser was removed too)

  // 2.2.0 (#327): set up again with the key already in the authenticator app - no new QR code to scan
  await page.getByRole("link", { name: "My account" }).click();
  await sec.getByRole("button", { name: "Set up two-step verification" }).click();
  await expect(sec.getByTestId("mfa-secret")).toBeVisible();
  await sec.getByText("Use my own key instead").click();
  await sec.getByLabel("Your authenticator key or otpauth link").fill("not a key 0189");
  await sec.getByRole("button", { name: "Use this key" }).click();
  await expect(sec.getByRole("alert")).toContainText("letters A-Z and the digits 2-7");
  await expect(sec.getByRole("alert")).not.toContainText("0189");
  await sec.getByLabel("Your authenticator key or otpauth link").fill(secret.toLowerCase().replace(/(.{4})/g, "$1 "));
  await sec.getByRole("button", { name: "Use this key" }).click();
  await expect(sec).toContainText("Using your own key.");
  await expect(sec.getByTestId("mfa-secret")).toHaveCount(0);
  await expect(sec.getByTestId("own-key-short")).toHaveCount(0);   // 32 characters, like PennyWarden's own
  await sec.getByLabel("Code from the app").fill(totp(secret, 1));
  await sec.getByRole("button", { name: "Turn on two-step verification" }).click();
  await expect(sec.getByRole("list", { name: "Recovery codes" }).locator("code")).toHaveCount(10);
  await sec.getByLabel("I have saved my recovery codes").check();
  await sec.getByRole("button", { name: "Continue" }).click();
  await expect(sec).toContainText("10 of 10 recovery codes unused");
  await logout(page);

  // a reset marked as a possible compromise: only a newly generated key
  await login(page, "admin");
  await page.getByRole("link", { name: "Users", exact: true }).click();
  await rowAction(page.getByRole("row", { name: /bm1/ }), "bm1", "Reset two-step");
  const dlg2 = page.getByRole("dialog");
  await dlg2.getByLabel("Reason (required)").fill("Phone stolen");
  await dlg2.getByLabel("Possible compromise").check();
  await dlg2.getByRole("button", { name: "Reset two-step verification" }).click();
  await expect(dlg2.getByRole("status")).toContainText("was reset");
  await dlg2.getByRole("button", { name: "Done" }).click();
  await logout(page);
  await login(page, "bm1");
  await page.getByRole("link", { name: "My account" }).click();
  await sec.getByRole("button", { name: "Set up two-step verification" }).click();
  await expect(sec.getByTestId("own-key-blocked")).toContainText("possible security problem");
  await expect(sec.getByLabel("Your authenticator key or otpauth link")).toHaveCount(0);
  await sec.getByRole("button", { name: "Cancel" }).click();
});

// ---------------------------------------------------------------- CR-023 / CR-024 / CR-025 backup and restore
const BACKUP_PASS = "e2e backup passphrase 2026";
let backupFile = "";

test("CR-023 / CR-025: Administrator creates an encrypted backup and restores it", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "Backups");
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
  // 2.2.0 (#319): What to restore - everything ticked, collapsed to All; here everything but Users
  const wtr = page.getByRole("group", { name: "What to restore" });
  await expect(wtr).toBeVisible({ timeout: 30_000 });
  await expect(wtr.getByLabel("Restore all")).toBeChecked();
  await wtr.getByText("— show the parts").click();
  await wtr.getByLabel("Restore Users").uncheck();
  await expect(wtr.getByLabel("Restore all")).not.toBeChecked();
  await wtr.getByRole("button", { name: "Review" }).click();
  await expect(wtr.getByTestId("restore-summary")).toContainText("Kept as it is now: Users");
  await expect(wtr.getByTestId("restore-summary")).toContainText("and the current audit log");
  await page.screenshot({ path: "e2e-screenshots/light-restore-what-to-restore.png", fullPage: true });
  await wtr.getByRole("button", { name: "Restore the chosen parts" }).click();
  await expect(page.getByRole("status")).toContainText("Restore complete", { timeout: 30_000 });
  await expect(page.getByTestId("restore-restored")).toContainText("Restored: data, settings.general");
  await page.screenshot({ path: "e2e-screenshots/light-restore-done.png", fullPage: true });
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({ timeout: 15_000 });
  await login(page, "admin");
  await page.getByRole("link", { name: "Audit Log", exact: true }).click();
  await expect(page.locator(".audit-action", { hasText: "Data restored from a backup" }).first()).toBeVisible();
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

test("#231: a server in testing mode shows the banner everywhere and the Testing tab to Administrators", async ({ page }) => {
  const port = 8801;
  const bundle = process.env.FM_BUNDLE;
  const dataDir = mkdtempSync(join(tmpdir(), "fm-test-srv-"));
  const args = ["--mode", "server", "--host", "127.0.0.1", "--no-browser", "--port", String(port), "--data-dir", dataDir];
  const child = spawn(bundle || process.env.FM_PYTHON || "python", bundle ? args : ["-m", "fmpoc", ...args],
    { cwd: existsSync(join(process.cwd(), "..", "backend")) ? join(process.cwd(), "..", "backend") : join(process.cwd(), "backend"),
      stdio: "ignore", env: { ...process.env, FM_TESTING_MODE: "true" } });
  try {
    const base = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 120; i++) {
      try { if ((await fetch(`${base}/api/health`)).ok) break; } catch { /* starting */ }
      await new Promise((r) => setTimeout(r, 250));
    }
    await page.goto(base + "/");
    await page.getByLabel("Organization / Workspace Name").fill("Test Server Org");
    await page.getByLabel("Administrator First Name").fill("Pat");
    await page.getByLabel("Administrator Last Name").fill("Example");
    await page.getByLabel("Administrator Username").fill("admin");
    await page.getByLabel("Administrator Email Address").fill("admin@example.org");
    await page.getByLabel("Password", { exact: true }).fill(PW);
    await page.getByLabel("Password Confirmation").fill(PW);
    await page.getByRole("button", { name: "Initialize" }).click();
    const secret = (await page.getByTestId("mfa-secret").textContent())!.replace(/\s/g, "");
    await page.getByLabel("Code from the app").fill(totp(secret));
    await page.getByRole("button", { name: "Turn on two-step verification" }).click();
    await page.getByLabel("I have saved my recovery codes").check();
    await page.getByRole("button", { name: "Continue" }).click();
    await setupQuestions(page);
    await expect(page.getByTestId("testing-banner")).toContainText("TESTING MODE");
    await page.goto(base + "/about/testing");
    const panel = page.getByRole("region", { name: "Testing" });
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("scheduled backups are off");
    await panel.getByRole("button", { name: "Check for updates now" }).click();
    await expect(panel.getByRole("status")).toContainText("Update check done.");
    await page.screenshot({ path: "e2e-screenshots/light-testing-mode.png", fullPage: true });
    // the setting is shown read-only
    await page.goto(base + "/about/settings");
    await expect(page.getByText("Testing mode (test server)")).toBeVisible();
    // and the sign-in page carries the banner too
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await expect(page.getByTestId("testing-banner")).toBeVisible();
  } finally {
    child.kill();
  }
});

test("#243: the published demo - built by the script, restored on a new install, banner, reset from the sign-in page", async ({ page }) => {
  test.setTimeout(240_000);
  test.skip(!!process.env.FM_BUNDLE && !process.env.FM_PYTHON, "builds the demo with Python from this checkout");
  const py = process.env.FM_PYTHON || "python";
  const root = existsSync(join(process.cwd(), "..", "scripts")) ? join(process.cwd(), "..") : process.cwd();
  const demoFile = join(mkdtempSync(join(tmpdir(), "fm-demo-")), "pennywarden-demo.fmbak");
  const built = spawnSync(py, [join(root, "scripts", "build_demo.py"), "--out", demoFile, "--python", py], { encoding: "utf-8", timeout: 200_000 });
  expect(built.status, built.stderr + built.stdout).toBe(0);
  const port = 8802;
  const bundle = process.env.FM_BUNDLE;
  const dataDir = mkdtempSync(join(tmpdir(), "fm-demo-install-"));
  const args = ["--no-browser", "--port", String(port), "--data-dir", dataDir];
  const child = spawn(bundle || py, bundle ? args : ["-m", "fmpoc", ...args], { cwd: join(root, "backend"), stdio: "ignore" });
  try {
    const base = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 120; i++) {
      try { if ((await fetch(`${base}/api/health`)).ok) break; } catch { /* starting */ }
      await new Promise((r) => setTimeout(r, 250));
    }
    await page.goto(base + "/");
    await page.getByRole("button", { name: "Restore from a backup instead" }).click();
    await page.getByLabel("Backup file (.fmbak)").setInputFiles(demoFile);
    await page.getByLabel("Backup passphrase").fill("pennywarden demo");
    await page.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByRole("status")).toContainText("Restore complete", { timeout: 60_000 });
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("demo-banner")).toContainText("DEMO");
    // the published sign-in, then a change the next reset undoes
    await page.getByLabel("Username").fill("demo-register");
    await page.getByLabel("Password").fill("Demo-PennyWarden-2026");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("demo-banner")).toBeVisible();
    await expect(page.getByTestId("demo-banner").getByRole("button", { name: "Remove the demo and start fresh" })).toHaveCount(0);
    await page.screenshot({ path: "e2e-screenshots/light-demo.png", fullPage: true });
    await page.getByRole("link", { name: "My account" }).click();
    await page.getByLabel("Current password").fill("Demo-PennyWarden-2026");
    await page.getByLabel("New password", { exact: true }).fill("Evaluator-Pass-77");
    await page.getByLabel("Confirm new password").fill("Evaluator-Pass-77");
    await page.getByRole("button", { name: "Change password" }).click();
    await expect(page.getByText("Password changed.")).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();
    // Reset demo data from the sign-in page: the published password works again
    const banner = page.getByTestId("demo-banner");
    await banner.getByRole("button", { name: "Reset demo data" }).click();
    // "Resetting…" until the reset is done, then the page reloads with the button as before
    await expect(banner.getByRole("button", { name: "Resetting…" })).toBeVisible();
    await expect(banner.getByRole("button", { name: "Reset demo data" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({ timeout: 30_000 });
    await page.getByLabel("Username").fill("demo-register");
    await page.getByLabel("Password").fill("Demo-PennyWarden-2026");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible({ timeout: 20_000 });
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
  await aboutTab(page, "Backups");
  await expect(page.getByRole("heading", { name: "Backup / Restore" })).toBeVisible();
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
  await page.getByRole("row", { name: /admin@example\.org/ }).getByRole("button", { name: "Edit" }).click();
  const dlg = page.getByRole("dialog", { name: "Edit Pat Example - admin" });
  await expect(dlg.getByLabel("Active")).toBeDisabled();
  await expect(dlg).toContainText("You cannot disable your own account.");
  await dlg.getByRole("button", { name: "Cancel" }).click();
  // another user's Active box stays available
  await page.getByRole("row", { name: /bm1@example\.org/ }).getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("dialog", { name: "Edit Bea Manager - bm1" }).getByLabel("Active")).toBeEnabled();
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
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(budgetSel).toHaveValue("");
});

// ---------------------------------------------------------------- 1.7.3 #52/#53: Budget Admin and Register Admin
test("#52 / #53: a Budget Admin deletes a draft budget and a Register Admin deletes an uncleared transaction", async ({ page }) => {
  await login(page, "admin");
  const adm = await apiAs(page);
  for (const [u, roles] of [["ba1", ["BUDGET_MANAGER", "BUDGET_ADMIN"]], ["ra1", ["REGISTER_USER", "REGISTER_ADMIN"]]] as const) {
    const r = await adm("/api/users", { first_name: "Test", last_name: "Person", username: u, email: `${u}@example.org`, display_name: `${u} person`, password: PW,
      security_domain: "FINANCIAL", roles });
    expect(r.status(), await r.text()).toBe(201);
  }
  // the extra role needs its base role
  const bad = await adm("/api/users", { first_name: "Test", last_name: "Person", username: "ba2", email: "ba2@example.org", display_name: "ba2 person", password: PW,
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
  await rowAction(row, "Index Fund", "Update balance");
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
  // 2.3.0 (#391): Correct the entry (reason required), then Retire it - it stays listed under Retired entries
  await rowAction(hist, `the balance as of ${d}`, "Correct…");
  const cor = page.getByRole("dialog", { name: `Correct the balance of $5,150.25 as of ${d}` });
  await cor.getByLabel("Balance", { exact: true }).fill("5105.25");
  await cor.getByLabel("Reason (required)").fill("typed 5150.25 for 5105.25");
  await cor.getByRole("button", { name: "Correct", exact: true }).click();
  await expect(cor).toHaveCount(0);
  await expect(hist.getByTestId("balance-corrected")).toHaveAttribute("title", /was \$5,150\.25 .*typed 5150\.25 for 5105\.25/);
  await rowAction(hist, `the balance as of ${d}`, "Retire…");
  const ret = page.getByRole("dialog", { name: `Retire the balance of $5,105.25 as of ${d}` });
  await ret.getByLabel("Reason (required)").fill("not a real statement");
  await ret.getByRole("button", { name: "Retire", exact: true }).click();
  await expect(ret).toHaveCount(0);
  await expect(hist.locator("tbody tr")).toHaveCount(1);
  await page.getByText("Retired entries (1)").click();
  await expect(page.getByRole("table", { name: "Retired balance entries" })).toContainText("not a real statement");
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

test("#284: a Budget Manager enters years before PennyWarden on History and imports more from a CSV", async ({ page }) => {
  await login(page, "bm1");
  const fys = await (await page.request.get("/api/fiscal-years")).json();
  const f41 = fys.find((f: any) => f.display_name === "FY2041");
  await page.goto(`/budgets?fiscal_year_id=${f41.id}`);
  await page.getByRole("button", { name: "History of 8900" }).click();
  const h = page.getByRole("dialog", { name: "History of 8900 Lineage" });
  const firstYear = Number((await h.locator(".hint").innerText()).match(/before FY(\d{4})/)![1]);
  const y1 = `FY${firstYear - 2}`, y2 = `FY${firstYear - 1}`;
  await h.getByRole("button", { name: "Add an earlier year" }).click();
  let add = page.getByRole("dialog", { name: "Add an earlier year to 8900 Lineage" });
  await add.getByLabel("Fiscal Year").fill(`FY${firstYear}`);
  await add.getByLabel("Budgeted").fill("80.00");
  await add.getByLabel("Actual").fill("75.50");
  await add.getByRole("button", { name: "Add" }).click();
  await expect(add.getByRole("alert")).toContainText("only years before the first Fiscal Year in PennyWarden");
  await add.getByLabel("Fiscal Year").fill(y2);
  await add.getByLabel("Note (optional)").fill("from the old treasurer's spreadsheet");
  await add.getByRole("button", { name: "Add" }).click();
  await expect(add).toHaveCount(0);
  const rows = h.getByRole("table", { name: "Budget history" }).locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.first()).toContainText(y2);
  await expect(rows.first()).toContainText("Entered");
  await expect(rows.first()).toContainText("$75.50");
  // correct it (a reason is required), then the History shows the new figure
  await h.getByRole("button", { name: `Correct ${y2}` }).click();
  const cor = page.getByRole("dialog", { name: `Correct ${y2}` });
  await cor.getByLabel("Actual").fill("76.00");
  await cor.getByLabel("Reason (required)").fill("Typo");
  await cor.getByRole("button", { name: "Save correction" }).click();
  await expect(rows.first()).toContainText("$76.00");
  await page.screenshot({ path: "e2e-screenshots/light-budget-history-entered.png" });
  await h.locator(".actions").getByRole("button", { name: "Close" }).click();

  // CSV import: preview first, then import the matched rows
  await page.getByRole("button", { name: "Import earlier years…" }).click();
  const imp = page.getByRole("dialog", { name: "Import earlier years (before PennyWarden)" });
  await expect(imp.getByRole("link", { name: "Download the template" })).toHaveAttribute("href", new RegExp(`fiscal_year_id=${f41.id}`));
  await imp.getByLabel("Or paste the CSV").fill(`year,budget code,budgeted,actual,note\n${y1},8900,70,65,\n${y2},8900,1,1,\n${y1},9999,1,1,\n`);
  await imp.getByRole("button", { name: "Preview" }).click();
  const prev = imp.getByRole("table", { name: "Import preview" });
  await expect(prev.locator("tbody tr")).toHaveCount(3);
  await expect(prev.locator("tbody tr").nth(1)).toContainText("Duplicate");
  await expect(prev.locator("tbody tr").nth(2)).toContainText("No budget 9999");
  await imp.getByRole("button", { name: "Import 1 year" }).click();
  await expect(imp.getByRole("status")).toContainText("1 year was entered.");
  await imp.getByRole("button", { name: "Done" }).click();
  // the Budget Review shows the entered years after the PennyWarden ones, labelled entered
  const rep = await (await page.request.get(`/api/reports/budget-review?fiscal_year_id=${f41.id}&years=-1`)).json();
  const entered = rep.years.filter((y: any) => y.entered).map((y: any) => y.display_name);
  expect(entered).toEqual(expect.arrayContaining([y1, y2]));
  const row = rep.expense.find((r: any) => r.code === "8900");
  const i = rep.years.findIndex((y: any) => y.display_name === y1);
  expect(row.history[i]).toMatchObject({ source: "ENTERED", budgeted: "70.00", actual: "65.00" });
});

test("#382: the Budget Review lists a budget of the years shown that is not in the chosen Fiscal Year", async ({ page }) => {
  await login(page, "bm1");
  const post = await apiAs(page);
  const fys = await (await page.request.get("/api/fiscal-years")).json();
  const f41 = fys.find((f: any) => f.display_name === "FY2041");
  const darts = await (await post("/api/budgets/former", { code: "460", name: "Darts League", budget_type: "EXPENSE" })).json();
  const anyBudget = (await (await page.request.get(`/api/budgets?fiscal_year_id=${f41.id}`)).json()).expense[0];
  const firstYear = (await (await page.request.get(`/api/budgets/${anyBudget.id}/history/entered`)).json()).first_year;
  const y = firstYear - 4;
  const e = await post(`/api/budgets/former/${darts.id}/entries`, { fiscal_year_label: `FY${y}`, budgeted: "120.00", actual: "95.00" });
  expect(e.status(), await e.text()).toBe(201);
  await page.goto("/reports");
  await page.getByRole("tab", { name: "Budget Review" }).click();
  await page.getByLabel("Budget Review Fiscal Year").selectOption(String(f41.id));
  await page.getByLabel("Prior years").selectOption("-1");
  await page.getByRole("button", { name: "Run report" }).click();
  const table = page.locator(".budget-review").getByRole("table", { name: "Budget Review" });
  const head = table.locator("th", { hasText: "460 Darts League" });
  await expect(head).toBeVisible();
  await expect(head.getByTestId("not-in-year")).toHaveText(`Not in FY2041, last FY${y}`);
  // nothing to keep: retire it again so later tests see the usual review
  const r = await page.request.post(`/api/budgets/former/${darts.id}/retire`, { headers: { "X-CSRF-Token": (await (await page.request.get("/api/auth/me")).json()).csrf_token }, data: { reason: "E2E" } });
  expect(r.status()).toBe(200);
});

test("#381: a budget from before PennyWarden is created, given a year and continued by a budget", async ({ page }) => {
  await login(page, "bm1");
  const post = await apiAs(page);
  const fys = await (await page.request.get("/api/fiscal-years")).json();
  const f41 = fys.find((f: any) => f.display_name === "FY2041");
  const bowl = await (await post("/api/budgets", { fiscal_year_id: f41.id, code: "8970", name: "Bowling", budget_type: "EXPENSE", amount: "50.00" })).json();
  const firstYear = (await (await page.request.get(`/api/budgets/${bowl.id}/history/entered`)).json()).first_year;
  const y = `FY${firstYear - 3}`;
  await page.goto(`/budgets?fiscal_year_id=${f41.id}`);
  await page.getByRole("button", { name: "Before PennyWarden…" }).click();
  const list = page.getByRole("dialog", { name: "Budgets from before PennyWarden" });
  await list.getByRole("button", { name: "New budget from before PennyWarden" }).click();
  const nf = page.getByRole("dialog", { name: "New budget from before PennyWarden" });
  await nf.getByLabel("Code").fill("450");
  await nf.getByLabel("Name").fill("Bowling Tournament");
  await nf.getByLabel("Type").selectOption("EXPENSE");
  await nf.getByRole("button", { name: "Create" }).click();
  const d = page.getByRole("dialog", { name: "450 Bowling Tournament (before PennyWarden)" });
  await expect(d.getByTestId("former-continued-by")).toContainText("No budget in PennyWarden continues it.");
  await d.getByRole("button", { name: "Add a year" }).click();
  const add = page.getByRole("dialog", { name: "Add a year to 450 Bowling Tournament" });
  await add.getByLabel("Fiscal Year").fill(y);
  await add.getByLabel("Budgeted").fill("800.00");
  await add.getByLabel("Actual").fill("760.00");
  await add.getByRole("button", { name: "Add" }).click();
  await expect(d.getByRole("table", { name: "Years before PennyWarden" })).toContainText("$760.00");
  await d.getByRole("button", { name: "Link to a budget…" }).click();
  const lk = page.getByRole("dialog", { name: "Link 450 Bowling Tournament to a budget" });
  await lk.getByLabel("Link Fiscal Year").selectOption(String(f41.id));
  await lk.getByLabel("Link budget").selectOption(String(bowl.id));
  await lk.getByRole("button", { name: "Link" }).click();
  await expect(d.getByTestId("former-continued-by")).toContainText("Continued by FY2041 8970 Bowling");
  await page.screenshot({ path: "e2e-screenshots/light-before-pennywarden.png" });
  await d.locator(".actions").getByRole("button", { name: "Close" }).last().click();
  await expect(list.getByRole("table", { name: "Budgets from before PennyWarden" })).toContainText("FY2041 8970 Bowling");
  await list.locator(".actions").getByRole("button", { name: "Close" }).last().click();
  // the budget's History shows the years and the link; Unlink removes them from its History
  await page.getByRole("button", { name: "History of 8970" }).click();
  const h = page.getByRole("dialog", { name: "History of 8970 Bowling" });
  await expect(h.getByTestId("former-link")).toContainText("continues 450 Bowling Tournament");
  await expect(h.getByRole("table", { name: "Budget history" })).toContainText(y);
  // the entered year shows the code and name it had then (ID and Name columns)
  const er = h.locator("tr.entered-row").filter({ hasText: y });
  await expect(er.locator("td").nth(1)).toHaveText("450");
  await expect(er.locator("td").nth(2)).toContainText("Bowling Tournament");
  await h.getByTestId("former-link").getByRole("button", { name: "Unlink" }).click();
  await expect(h.getByTestId("former-link")).toContainText("Not linked to a budget from before PennyWarden.");
  await expect(h.getByRole("table", { name: "Budget history" })).not.toContainText(y);
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
  await aboutTab(page, "General");
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
  await dlg.getByLabel("Goal (optional)").fill("500");   // 2.3.0 (#372)
  await expect(dlg.getByText("Filter in use:")).toBeVisible();
  await expect(dlg.getByTestId("fr-preview")).toContainText("0 of");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("[data-code=FILTER]")).toBeVisible();
  await expect(page.getByTestId("fr-totals")).toContainText("$0.00");
  await expect(page.getByTestId("fr-goal")).toContainText("$500.00");
  await expect(page.getByTestId("fr-goal")).toContainText("$500.00 to go");
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

test("2.1.0 (#278): bucket categories with subtotals, reorder, and Charge / Less on a line", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  await page.getByRole("button", { name: "New category" }).click();
  let dlg = page.getByRole("dialog", { name: "New category" });
  await dlg.getByLabel("Category name").fill("Day-of event");
  await dlg.getByRole("button", { name: "Save" }).click();
  await page.getByRole("button", { name: "New bucket" }).click();
  dlg = page.getByRole("dialog", { name: "New bucket" });
  await dlg.getByLabel("Bucket name").fill("Raffle");
  await dlg.getByLabel("Category (optional)").selectOption({ label: "Day-of event" });
  await dlg.getByRole("button", { name: "Save" }).click();
  const table = page.getByTestId("fr-buckets");
  await expect(table.locator("tr.category-row")).toContainText("Day-of event");
  await expect(table).toContainText("Day-of event subtotal");
  // reorder: Raffle before Food sales
  await page.getByRole("button", { name: "Reorder…" }).click();
  dlg = page.getByRole("dialog", { name: "Reorder categories and buckets" });
  await dlg.getByRole("button", { name: "Move Raffle up" }).click();
  await dlg.getByRole("button", { name: "Save order" }).click();
  await expect(dlg).toHaveCount(0);
  // Charge less a credit on a line (line 2 has a $1.00 cash float)
  await page.getByTestId("fr-lines").getByRole("button", { name: /^Manage line/ }).nth(1).click();
  dlg = page.getByRole("dialog", { name: "Manage transaction line" });
  const raffle = dlg.locator(".fr-bucket-row").filter({ hasText: "Raffle" });
  await raffle.getByLabel("Charge less a credit for Raffle").check();
  await raffle.getByRole("button", { name: "All remaining" }).click();
  await raffle.getByLabel("Less for Raffle").fill("0.50");
  await raffle.getByLabel("Less description for Raffle").fill("Card fee");
  // build 4-6 feedback: lump cash shows as "Cash" on the reports
  await raffle.getByLabel("Show a different contributor for Raffle").check();
  await raffle.getByLabel("Contributor shown for Raffle").fill("Cash");
  await expect(dlg.getByTestId("fr-line-remaining")).toContainText("unassigned $0.50");
  // 2.1.0 (#303): the part in no bucket can show a different contributor too
  await dlg.getByLabel("Show a different contributor for the part in no bucket").check();
  await dlg.getByLabel("Contributor shown for the part in no bucket").fill("Change jar");
  await page.screenshot({ path: "e2e-screenshots/light-fundraiser-charge-less.png" });
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toHaveCount(0);
  await expect(page.getByTestId("fr-lines")).toContainText("not in a bucket: shown as “Change jar”");
  await expect(page.getByTestId("fr-lines").locator(".fr-bucket").filter({ hasText: "Raffle" })).toContainText("less $0.50 Card fee");
  await expect(page.getByTestId("fr-lines").locator(".fr-bucket").filter({ hasText: "Raffle" })).toContainText("shown as “Cash”");
  await page.screenshot({ path: "e2e-screenshots/light-fundraiser-categories.png", fullPage: true });
  // delete the category: Raffle stays, uncategorized
  page.once("dialog", (d) => d.accept());
  await table.getByRole("button", { name: "Actions for category Day-of event" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await expect(table.locator("tr.category-row")).toHaveCount(0);
  await expect(table).toContainText("Raffle");
  await logout(page);
});

test("2.1.0 (#277): next year's fundraiser continues the series, prior years entered, Fiscal Year report and deck", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  await page.getByRole("button", { name: "Create next year's…" }).click();
  let dlg = page.getByRole("dialog", { name: "New fundraiser (next year)" });
  await expect(dlg.getByLabel("Name")).not.toHaveValue("");
  await expect(dlg.getByLabel("Continues from (previous fundraiser)")).not.toHaveValue("");
  await dlg.getByLabel("Name").fill("Harvest Dinner next year");
  await dlg.getByRole("button", { name: "Create fundraiser" }).click();
  await expect(page.getByTestId("fr-series")).toContainText("continues Harvest Dinner");
  // the series list: enter a year before PennyWarden
  await page.getByRole("link", { name: "Fundraisers" }).first().click();
  await page.getByRole("link", { name: "Fundraiser series" }).click();
  await page.getByRole("button", { name: "Enter a prior year…" }).first().click();
  dlg = page.getByRole("dialog", { name: /Enter a prior year/ });
  await dlg.getByLabel("Fiscal Year (include the year)").fill("FY2019");
  await dlg.getByLabel("Amount raised (net)").fill("640.00");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("section.card").first()).toContainText("FY2019");
  await page.screenshot({ path: "e2e-screenshots/light-fundraiser-series.png", fullPage: true });
  // the Fiscal Year report for the ticked fundraisers
  await page.getByRole("link", { name: "← Fundraisers" }).click();
  await expect(page.getByTestId("fundraiser-list")).toBeVisible();
  await page.getByRole("button", { name: "Fiscal Year report…" }).click();
  dlg = page.getByRole("dialog", { name: "Fiscal Year fundraising report" });
  await dlg.getByLabel("Include targeted total").check();
  await dlg.getByLabel(/Notes \(printed/).fill("Matching gifts expected.");
  await dlg.getByRole("button", { name: "Save notes" }).click();
  await expect(dlg.getByRole("button", { name: "Save notes" })).toBeDisabled();
  const pdf = await page.request.get((await dlg.getByRole("link", { name: "Report (PDF)" }).getAttribute("href"))!);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  const deck = await page.request.get((await dlg.getByRole("link", { name: "Presentation" }).getAttribute("href"))!);
  expect(deck.status()).toBe(200);
  expect(deck.headers()["content-type"]).toContain("presentationml");
  await dlg.getByRole("button", { name: "Done" }).click();
  await logout(page);
});

test("2.1.0 (#292): prior years for an event with nothing earlier in PennyWarden - Start a series, Enter prior years", async ({ page }) => {
  await login(page, "bm1");
  // on a fundraiser already in a series, Enter prior years… opens that series' entry
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner", exact: true }).click();
  await page.getByRole("button", { name: "Enter prior years…" }).click();
  let dlg = page.getByRole("dialog", { name: "Enter a prior year — Harvest Dinner" });
  await expect(dlg).toBeVisible();
  await dlg.getByRole("button", { name: "Cancel" }).click();
  // Spring Fair 2028 continues from nothing: start its series from the series page
  await page.getByRole("button", { name: "Start a series…" }).click();
  dlg = page.getByRole("dialog", { name: "Start a series" });
  await dlg.getByLabel("Fundraiser").selectOption((await dlg.locator("option", { hasText: "Spring Fair 2028" }).getAttribute("value"))!);
  await expect(dlg).toContainText("The series will be named Spring Fair");
  await page.screenshot({ path: "e2e-screenshots/light-fundraiser-start-series.png" });
  await dlg.getByRole("button", { name: "Start series" }).click();
  dlg = page.getByRole("dialog", { name: "Enter a prior year — Spring Fair" });
  await dlg.getByLabel("Fiscal Year (include the year)").fill("FY2025");
  await dlg.getByLabel("Amount raised (net)").fill("410.00");
  await dlg.getByRole("button", { name: "Save" }).click();
  const card = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "Spring Fair" }) });
  await expect(card).toContainText("Spring Fair 2028");
  await expect(card).toContainText("FY2025");
  await expect(card).toContainText("$410.00");
  // 2.3.0 (#390): Correct it as estimated - the note is required once Estimated is ticked, then the year is marked *
  await card.getByRole("button", { name: "Correct…" }).click();
  dlg = page.getByRole("dialog", { name: "Correct FY2025 — Spring Fair" });
  await dlg.getByLabel("Estimated").check();
  await dlg.getByLabel("Reason for the correction (required)").fill("records were partial");
  await expect(dlg.getByRole("button", { name: "Save" })).toBeDisabled();
  await dlg.getByLabel("Note (required: why it is estimated)").fill("only the bank deposit is known");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toHaveCount(0);
  await expect(card.getByTestId("estimated-mark")).toBeVisible();
  await expect(card).toContainText("only the bank deposit is known");
  await logout(page);
});

test("2.2.0 (#302, #351): add a second same-year fundraiser to a series; years newest first, flipped and remembered", async ({ page }) => {
  await login(page, "bm1");
  // a second Spring Fair in the same year: nothing earlier to continue from, so Add to a series…
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("button", { name: "New fundraiser" }).click();
  let dlg = page.getByRole("dialog", { name: "New fundraiser" });
  await dlg.getByLabel("Name").fill("Spring Fair Encore 2028");
  await dlg.getByLabel("Event start date").fill("2028-05-06");
  await dlg.getByRole("button", { name: "Create fundraiser" }).click();
  await expect(page.getByTestId("fr-series")).toContainText("Not linked to an earlier year");
  await page.getByRole("button", { name: "Add to a series…" }).click();
  dlg = page.getByRole("dialog", { name: "Add to an existing series" });
  await dlg.getByLabel("Series").selectOption((await dlg.locator("option", { hasText: /^Spring Fair$/ }).getAttribute("value"))!);
  await dlg.getByRole("button", { name: "Add to series" }).click();
  await expect(page.getByTestId("fr-series")).toContainText("Spring Fair");
  // the series page: one list, newest year first (same year: newest start first), with the hint
  await page.getByRole("link", { name: "← Fundraisers" }).click();
  await page.getByRole("link", { name: "Fundraiser series" }).click();
  await expect(page.getByTestId("series-twice-hint")).toContainText("more than once a year");
  const card = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "Spring Fair", exact: true }) });
  const rows = card.locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("Spring Fair Encore 2028");
  await expect(rows.nth(1)).toContainText("Spring Fair 2028");
  await expect(rows.nth(2)).toContainText("FY2025");
  await expect(page.locator(".sort-note")).toHaveCount(0);
  // Year flips every table, and the choice is remembered
  await card.getByRole("button", { name: "Year", exact: true }).click();
  await expect(page.locator(".sort-note")).toContainText("Sorted by year, oldest first");
  await expect(rows.nth(0)).toContainText("FY2025");
  await expect(rows.nth(1)).toContainText("Spring Fair Encore 2028");   // within a year: unchanged
  for (const th of await page.locator("section.card thead th").filter({ hasText: "Year" }).all()) await expect(th).toHaveAttribute("aria-sort", "ascending");
  await logout(page);
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Fundraiser series" }).click();
  await expect(rows.nth(0)).toContainText("FY2025");
  await page.getByRole("button", { name: "Reset to default" }).click();
  await expect(page.locator(".sort-note")).toHaveCount(0);
  await expect(rows.nth(0)).toContainText("Spring Fair Encore 2028");
  await logout(page);
});

// ---------------------------------------------------------------- v1.6.2 CR-035: fundraiser report
test("CR-035: fundraiser report PDF; Audit and Close reports can include fundraisers", async ({ page }) => {
  await login(page, "bm1");
  await page.getByRole("link", { name: "Fundraisers" }).click();
  await page.getByRole("link", { name: "Harvest Dinner" }).click();
  // 2.1.0 (#275): the page's Report… is the stakeholder report (PDF or Word), with options
  await page.getByRole("button", { name: "Report…" }).first().click();
  const rd = page.getByRole("dialog", { name: "Fundraiser report" });
  await rd.getByLabel(/Show contributor names/).uncheck();
  // 2.1.0 (#300): Harvest Dinner is in a series - year over year can be left out (report and presentation)
  await expect(rd.getByLabel(/Include year over year/)).toBeChecked();
  await rd.getByLabel(/Include year over year/).uncheck();
  expect(await rd.getByRole("link", { name: "Presentation" }).getAttribute("href")).toContain("history=false");
  const href = await rd.getByRole("link", { name: "Report (PDF)" }).getAttribute("href");
  expect(href).toContain("names=false");
  expect(href).toContain("history=false");
  const pdf = await page.request.get(href!);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  const word = await page.request.get((await rd.getByRole("link", { name: "Report (Word)" }).getAttribute("href"))!);
  expect(word.status()).toBe(200);
  expect(word.headers()["content-type"]).toContain("wordprocessingml");
  // 2.1.0 (#276): the presentation, same options
  const deck = await page.request.get((await rd.getByRole("link", { name: "Presentation" }).getAttribute("href"))!);
  expect(deck.status()).toBe(200);
  expect(deck.headers()["content-type"]).toContain("presentationml");
  expect(deck.headers()["content-disposition"]).toContain("-presentation.pptx");
  await rd.getByRole("button", { name: "Done" }).click();
  // Budget Manager: summary notes and Mark results final
  const card = page.locator("section").filter({ has: page.getByRole("heading", { name: "Stakeholder report" }) });
  await card.getByLabel(/Summary notes/).fill("Thanks to every volunteer.");
  await card.getByRole("button", { name: "Save notes" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  await card.getByRole("button", { name: "Mark results final" }).click();
  await expect(page.getByTestId("fr-report-status")).toContainText("Final (marked final)");
  await page.screenshot({ path: "e2e-screenshots/light-fundraiser-stakeholder-report.png", fullPage: true });
  await card.getByRole("button", { name: "Undo final" }).click();
  await expect(page.getByTestId("fr-report-status")).not.toContainText("marked final");
  // the audit detail moved to Reports -> Fundraiser detail (audit)
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByRole("tab", { name: "Fundraiser detail (audit)" }).click();
  const det = await page.getByRole("link", { name: "Open detail PDF" }).getAttribute("href");
  expect(det).toMatch(/\/api\/fundraisers\/\d+\/report$/);
  expect((await page.request.get(det!)).status()).toBe(200);
  await page.getByRole("tab", { name: "End of Year Audit" }).click();
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
  await rowAction(page, "File the annual return", "Resolve…");
  dlg = page.getByRole("dialog", { name: "Resolve reminder" });
  await dlg.getByLabel("Note (optional)").fill("Filed online");
  await dlg.getByRole("button", { name: "Mark as resolved" }).click();
  await expect(page.getByText("Nothing needs your attention.")).toBeVisible();
  await expect(page.getByTestId("bell-count")).toHaveCount(0);
  await page.getByRole("tab", { name: "Resolved" }).click();
  await expect(page.getByTestId("reminder")).toContainText("Filed online");
  await rowAction(page, "File the annual return", "Reopen");
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
  await rowAction(page, "Reconcile the bank statement", "Resolve…");
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
  await rowAction(page, "Reconcile the bank statement", "Delete");
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
    await page.getByLabel("Administrator First Name").fill("Pat");
    await page.getByLabel("Administrator Last Name").fill("Example");
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

// ---------------------------------------------------------------- 2.2.0 #348: comparisons before any data
test("#348: a Compare Date before any data uses the earliest data, marked on the review screen", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  const today = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByRole("tab", { name: "Financial Flow" }).click();
  await page.getByLabel("Title").fill("E2E compare");
  await page.getByLabel("From Date").fill(today);
  const notes = page.getByRole("checkbox", { name: "Show notes on substituted starting values" });
  await expect(notes).toBeDisabled();
  await page.getByRole("checkbox", { name: "Include Bank Balances" }).check();
  await page.getByLabel("Compare Date").fill("2001-01-01");
  await expect(notes).toBeEnabled();
  await expect(notes).not.toBeChecked();                     // off by default
  await page.getByRole("button", { name: "Review transactions" }).click();
  const subs = page.getByTestId("flow-substitutions");
  await expect(subs).toContainText("starting balance is the first recorded balance");
  await expect(subs).toContainText("(no data on 2001-01-01)");
  await expect(subs.locator(".subst-marker").first()).toHaveAttribute("title", /Opening Balance Date|Update balance/);
});

// ---------------------------------------------------------------- 1.8.0 #113: Forgot password
test("#113: security questions at the first sign-in, Forgot password, notices for the user and the Administrators", async ({ page }) => {
  await login(page, "admin");
  const adm = await apiAs(page);
  const r = await adm("/api/users", { first_name: "Frankie", last_name: "Pass", username: "fp1", email: "fp1@example.org", display_name: "Frankie Pass", password: PW,
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
  await aboutTab(page, "Backups");
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
  // 2.1.0 (#233): the only backup is the newest daily one (and the first of its week and month)
  await expect(hist.locator("tbody tr").first().getByTestId("kept-as")).toContainText("Daily");
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
  await aboutTab(page, "General");
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
  await page.screenshot({ path: "e2e-screenshots/light-check-setup.png", fullPage: true });
  // a signer with a (synthetic) signature image; only a SAMPLE preview is ever shown
  // 2.3.0 (#395): signers live on the shared Signers page, tagged for the areas they sign
  await page.goto("/signers");
  await page.getByRole("button", { name: "Add signer…" }).click();
  const sd = page.getByRole("dialog", { name: "Add signer" });
  await sd.getByLabel(/^Name/).fill("Jordan Sample");
  await sd.getByLabel("Title (optional)").fill("Treasurer");
  await expect(sd.getByLabel("Checks")).toBeChecked();
  await sd.getByLabel(/Signature image/).setInputFiles({ name: "signature.png", mimeType: "image/png", buffer: await samplePng() });
  await sd.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("img", { name: "Sample of Jordan Sample's signature" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/light-signers.png", fullPage: true });
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
  await page.getByRole("button", { name: "Create payment…" }).click();
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
  await page.getByRole("button", { name: "Reprint check or letter…" }).click();
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
test("#164: a Register User enters a two-invoice payment, sees the check amount in words, prints it; the register offers Reprint check or letter… afterwards", async ({ page }) => {
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
  // build 13: in the register a printed check's withdrawal offers Reprint check or letter… (an unprinted one Create payment…),
  // which opens the same print screen over the register
  await recent.getByRole("link", { name: "Open in register" }).first().click();
  await expect(page.getByRole("button", { name: "Reprint check or letter…" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create payment…" })).toHaveCount(0);
  await page.getByRole("button", { name: "Reprint check or letter…" }).click();
  const again = page.getByRole("dialog", { name: /^Print check – transaction #\d+$/ });
  await expect(again.getByRole("img", { name: "Check preview drawn to scale" })).toContainText("SAMPLE SUPPLY COMPANY, INC");
  await again.getByRole("button", { name: "Close" }).first().click();
  await expect(page.getByRole("heading", { name: "Register", level: 1 })).toBeVisible();
});

// 2.1.1 (product owner, 2026-10-23): an electronic payment's "Letter or envelope…" opened an empty dialog when the
// workspace had no cover letter or envelope templates - it is disabled then and says why
async function electronicPaymentDetails(page: Page) {
  await page.goto("/register?account=1&search=ACH-20261120");
  const row = page.getByRole("row", { name: /2026-11-20/ });
  await row.getByRole("button", { name: /Details for transaction/ }).click();
  return page.getByRole("button", { name: "Letter or envelope…" });
}

test("2.1.1: without cover letter or envelope templates, an electronic payment's Letter or envelope… is disabled and says why", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  const btn = await electronicPaymentDetails(page);
  await expect(btn).toBeDisabled();
  await expect(page.locator(".disabled-hint")).toHaveAttribute("title", /no cover letter or envelope templates yet.*Payments Setup/);
  await expect(btn).toHaveAccessibleDescription(/no cover letter or envelope templates yet/);
  await logout(page);
});

// 2.1.2 (#344, product owner, 2026-10-23): changing a single-line deposit's Entity saved without error but changed
// nothing - the hidden line Entity put the old one back
test("2.1.2: changing a deposit's Entity in the edit form saves it", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  const mk = async (name: string) => (await (await post("/api/entities", { entity_type: "ORGANIZATION", organization_name: name, confirmations: ["DUPLICATE_ENTITY"] })).json()).id;
  const oldId = await mk("Sample Bell Club Old");
  const newId = await mk("Sample Bell Club, Inc");
  const opts = await (await page.request.get("/api/budgets/selectable?fiscal_year_id=1&transaction_type=DEPOSIT")).json();
  const body: any = { bank_account_id: 1, transaction_type: "DEPOSIT", transaction_date: "2026-11-20", entity_id: oldId,
    allocations: [{ budget_id: opts[0].id, amount: "360.00", description: "Cash box seed" }] };
  let tr = await post("/api/transactions", body);
  if (tr.status() === 409) {   // confirm whatever warnings the earlier tests' data raises (not what is tested here)
    body.confirmations = (await tr.json()).error.warnings.map((w: any) => w.code);
    tr = await post("/api/transactions", body);
  }
  expect(tr.status()).toBe(201);
  const t = await tr.json();
  await page.goto(`/register?account=1&txn=${t.id}`);
  const row = page.locator(`#txn-${t.id}`);
  await expect(row.getByRole("button", { name: `Details for transaction ${t.id}` })).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const dlg = page.getByRole("dialog", { name: `Edit transaction #${t.id}` });
  await dlg.getByRole("combobox", { name: "Entity (payer)" }).fill("Sample Bell Club, Inc");
  await page.getByRole("option", { name: /Sample Bell Club, Inc/ }).click();
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toHaveCount(0);
  const saved = await (await page.request.get(`/api/transactions/${t.id}`)).json();
  expect(saved.entity.id).toBe(newId);
  expect(saved.allocations[0].entity.id).toBe(newId);
  await logout(page);
});

// ---------------------------------------------------------------- 2.3.0 build 8: one setup layout (#394)
test("#394: setup editors put a locked preview beside the settings on wide screens and at the top (Keep at the top) on narrow ones", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await login(page, "admin");
  await page.getByRole("link", { name: "Payments Setup" }).click();
  await page.getByRole("button", { name: "New cover letter" }).click();
  const preview = page.getByTestId("setup-preview");
  const general = page.getByRole("heading", { name: "Signed by" });
  await expect(page.getByRole("img", { name: "Cover letter preview" })).toBeVisible();
  // wide: the preview is to the right of the settings, Keep at the top is not offered, and it stays on screen
  const pb = (await preview.boundingBox())!, gb = (await general.boundingBox())!;
  expect(pb.x).toBeGreaterThan(gb.x + gb.width / 2);
  await expect(page.getByLabel("Keep at the top")).toBeHidden();
  await general.scrollIntoViewIfNeeded();
  await page.locator(".content").evaluate((el) => el.scrollTo(0, el.scrollHeight));
  await expect(page.getByRole("img", { name: "Cover letter preview" })).toBeInViewport();
  // narrow: the preview is at the top of the page, with Keep at the top
  await page.setViewportSize({ width: 900, height: 900 });
  await page.locator(".content").evaluate((el) => el.scrollTo(0, 0));
  const pb2 = (await page.getByRole("heading", { name: /^Preview/ }).boundingBox())!;
  const gb2 = (await page.getByRole("heading", { name: "Signed by" }).boundingBox())!;
  expect(pb2.y).toBeLessThan(gb2.y);
  await page.getByLabel("Keep at the top").check();
  await page.locator(".content").evaluate((el) => el.scrollTo(0, el.scrollHeight));
  await expect(page.getByRole("img", { name: "Cover letter preview" })).toBeInViewport({ ratio: 0.3 });
  await page.getByLabel("Keep at the top").uncheck();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  await logout(page);
});

// ---------------------------------------------------------------- 2.0.0 build 3: cover letters, envelopes (#165, #166)
test("#165-#166: Administrator sets up a cover letter and an envelope; a Register User records a handwritten check and prints both", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "Payments Setup" }).click();
  await page.getByRole("button", { name: "New cover letter" }).click();
  await expect(page.getByRole("heading", { name: "Cover letter: Invoice payment letter" })).toBeVisible();
  // the editor has the page to itself: no check styles or signers above it
  await expect(page.getByRole("heading", { name: "Check styles" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Signers and signatures" })).toHaveCount(0);
  // #186: a live preview with sample data, and collapsible sections
  await expect(page.getByRole("img", { name: "Cover letter preview" })).toBeVisible();
  await page.getByRole("button", { name: "Signed by" }).click();
  await expect(page.getByLabel("Name when there is no signer")).toBeHidden();
  await page.getByRole("button", { name: "Signed by" }).click();
  // build 13: a new letter is a draft until saved; a logo can be added once it is saved
  await expect(page.getByTestId("draft-note")).toBeVisible();
  await expect(page.getByLabel("Logo image")).toHaveCount(0);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await expect(page.getByTestId("draft-note")).toHaveCount(0);
  // #176: a logo (a tiny PNG made here: synthetic) and #177: the address for a window envelope
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAADAAAAAYCAIAAAAzn+mLAAAAN0lEQVR4nO3OMQHAIADAMEDINCERqfv39GRHoiDz2Wf8ybod+BIqQkWoCBWhIlSEilARKkJFqLyoawE+y3CGBgAAAABJRU5ErkJggg==", "base64");
  await page.getByLabel("Logo image").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: png });
  await expect(page.getByRole("img", { name: "The letter's logo" })).toBeVisible();
  await page.getByLabel("Address for a window envelope").selectOption("LETTER");
  await expect(page.getByLabel("Payee address – right (in)")).toBeVisible();
  await page.getByLabel("Address for a window envelope").selectOption("NONE");
  // 2.1.0 (#247): fold marks (a saved template: choosing a window doesn't change them) - on the front, a longer tick
  await expect(page.getByLabel("Print fold marks")).toHaveValue("NONE");
  await page.getByLabel("Print fold marks").selectOption("FRONT");
  await page.getByLabel("Tick length").fill("0.2");
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
  await expect(page.getByRole("heading", { name: "Cover letters" })).toHaveCount(0);
  // the return address starts as the default letter's letterhead
  await expect(page.getByLabel("Return address line 2", { exact: true })).toHaveValue("100 Example Street, Sampletown");
  await expect(page.getByRole("img", { name: "Envelope preview" })).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  const letters = page.getByRole("region", { name: "Cover letters" });
  const envelopes = page.getByRole("region", { name: "Envelopes" });
  await expect(letters.getByRole("row", { name: /Invoice payment letter/ })).toContainText("Default");
  await expect(envelopes.getByRole("row", { name: /#10 envelope/ })).toContainText("Default");
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
  await page.getByRole("button", { name: "Create payment…" }).click();
  const dlg = page.getByRole("dialog", { name: `Print check – transaction #${t.id}` });
  await dlg.getByLabel("I'm writing the check by hand").check();
  await dlg.getByLabel("Check number you wrote").fill("8301");
  await dlg.getByLabel("Type the check number again").fill("8310");
  await expect(dlg.getByText("The two numbers don't match.")).toBeVisible();
  await expect(dlg.getByRole("button", { name: "Record check number" })).toBeDisabled();
  await dlg.getByLabel("Type the check number again").fill("8301");
  await dlg.getByRole("button", { name: "Record check number" }).click();
  await expect(dlg.getByText("Check number #8301 is recorded for this payment.")).toBeVisible();
  // 2.1.0 (#247): the letter's fold marks start from the template; on the back shows the two-sided banner
  await expect(dlg.getByLabel("Fold marks", { exact: true })).toHaveValue("FRONT");
  await dlg.getByLabel("Fold marks", { exact: true }).selectOption("BACK");
  await expect(dlg.getByTestId("fold-back-banner")).toContainText("Print on both sides of the paper");
  await page.screenshot({ path: "e2e-screenshots/light-letter-fold-marks.png" });
  await dlg.getByRole("button", { name: "My letter printer settings" }).click();
  await dlg.getByLabel("Fold marks on my letters").selectOption("BACK");
  await dlg.getByRole("button", { name: "Save my setting" }).click();
  await expect(dlg.getByRole("button", { name: "Hide (adjusted)" })).toBeVisible();
  await dlg.getByLabel("Fold marks on my letters").selectOption("TEMPLATE");
  await dlg.getByRole("button", { name: "Save my setting" }).click();
  await expect(dlg.getByRole("button", { name: "Hide", exact: true })).toBeVisible();
  await dlg.getByLabel("Fold marks", { exact: true }).selectOption("FRONT");
  await expect(dlg.getByTestId("fold-back-banner")).toHaveCount(0);
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

test("2.1.1: once a template exists, an electronic payment's Letter or envelope… opens the cover letter and envelope choices", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  const btn = await electronicPaymentDetails(page);
  await expect(btn).toBeEnabled();
  await btn.click();
  const dlg = page.getByRole("dialog", { name: /^Letter and envelope – transaction #\d+$/ });
  await expect(dlg.getByRole("heading", { name: "Cover letter and envelope" })).toBeVisible();
  await expect(dlg).toContainText("This payment was made electronically");
  await dlg.getByRole("button", { name: "Close" }).first().click();
  await logout(page);
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
  // #186: the stubs are drawn under the check in the preview
  await expect(page.getByTestId("stub-preview")).toContainText("OFFICE COPY");
  // 2.1.0 (#246): the layout - check at the bottom with two stubs above it, then back to the top
  await expect(page.getByLabel("Check position")).toHaveValue("TOP");
  await expect(page.getByLabel("Stubs", { exact: true })).toHaveValue("TWO");
  await expect(page.getByLabel("Stub 1 copy").locator("option:checked")).toHaveText("Invoice stub");
  const restubbed = page.waitForResponse((r) => r.url().includes("/api/checks/sample-stubs"));
  await page.getByLabel("Check position").selectOption("BOTTOM");
  await restubbed;                                                     // the preview's stubs follow the new layout
  await expect(page.getByLabel("Check top")).toHaveValue("7.5");
  await expect(page.getByLabel("Stub 1 top")).toHaveValue("0");
  await expect(page.getByTestId("stub-preview")).toContainText("OFFICE COPY");
  await page.getByTestId("voucher-layout").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e-screenshots/light-voucher-bottom-layout.png" });
  await page.getByRole("img", { name: "Check preview drawn to scale" }).screenshot({ path: "e2e-screenshots/light-voucher-bottom-preview.png" });
  await page.getByLabel("Check position").selectOption("TOP");
  await expect(page.getByLabel("Check top")).toHaveValue("0");
  await expect(page.getByLabel("Stub 2 copy")).toHaveValue("OFFICE");
  await page.getByRole("button", { name: "Save check style" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.getByRole("button", { name: "Test print", exact: true }).click();
  const tp = page.getByRole("dialog", { name: "Test print" });
  await expect(tp.getByRole("button", { name: "Print…" })).toBeVisible();
  await tp.getByRole("button", { name: "Close" }).first().click();
  await page.getByRole("button", { name: "Back to check styles" }).click();
  await page.goto("/signers");   // 2.3.0 (#395)
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
  await page.getByRole("button", { name: "Create payment…" }).click();
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

test("#126: an Administrator renames the organization, sees the effective settings and sets the backup reminder", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "General");
  const orgPanel = page.getByRole("region", { name: "Organization" });
  await page.getByLabel("Organization name").fill("E2E Org Renamed");
  await orgPanel.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".brand")).toContainText("E2E Org Renamed");
  await page.getByLabel("Organization name").fill("E2E Org");
  await orgPanel.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".brand")).toContainText("E2E Org");
  // 2.1.0 (#314): the organization profile - address, phone, email and EIN (made up). Typed straight away, while the
  // rename may still be saving: what is typed must not be overwritten when that save answers.
  await orgPanel.getByLabel("Street address").fill("100 Example Street");
  await orgPanel.getByLabel("City").fill("Sampletown");
  await orgPanel.getByLabel("State").fill("US");
  await orgPanel.getByLabel("ZIP code").fill("55555");
  await orgPanel.getByLabel("Email").fill("office@example.org");
  // the phone is formatted like an entity's when the field is left
  await orgPanel.getByLabel("Phone").fill("5555550142");
  await orgPanel.getByLabel("Phone").blur();
  await expect(orgPanel.getByLabel("Phone")).toHaveValue("(555) 555-0142");
  await orgPanel.getByLabel("EIN (Employer Identification Number)").fill("123456789");
  await orgPanel.getByLabel("EIN (Employer Identification Number)").blur();
  await expect(orgPanel.getByLabel("EIN (Employer Identification Number)")).toHaveValue("12-3456789");
  await orgPanel.getByRole("button", { name: "Save" }).click();
  await expect(orgPanel.getByRole("status")).toHaveText("Saved.");
  await expect(orgPanel.getByLabel("Street address")).toHaveValue("100 Example Street");
  await expect(orgPanel.getByLabel("City")).toHaveValue("Sampletown");
  await expect(orgPanel.getByLabel("Phone")).toHaveValue("(555) 555-0142");
  await page.screenshot({ path: "e2e-screenshots/light-organization-profile.png" });
  await aboutTab(page, "Settings");
  const settings = page.getByRole("region", { name: "Settings" });
  await expect(settings.getByRole("row", { name: /Session idle timeout \(minutes\) 30 default/ })).toBeVisible();
  await expect(settings.getByRole("button", { name: "Save settings" })).toHaveCount(0);   // local install: view only
  // 2.3.0 (#379): the update channel is the one setting editable on a local install - here it's set by the
  // environment (FM_UPDATE_CHANNEL in the E2E server), so it is shown with its plain-language name and stays locked
  await expect(settings.getByRole("row", { name: /Update channel Production releases only environment/ })).toBeVisible();
  await aboutTab(page, "Backups");
  await page.getByLabel("Warn when there is no backup for (days, 0 = never)").fill("3");
  await page.getByRole("region", { name: "Backup reminder" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("region", { name: "Backup reminder" }).getByRole("status")).toHaveText("Saved.");
});

test("#127-#129: an Administrator sees the signed-in sessions, downloads diagnostics and checks the health", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "Security");
  const s = page.getByRole("region", { name: "Signed-in sessions" });
  await expect(s.getByRole("row", { name: /admin.*you, this session/ })).toBeVisible();
  // your own session can't be ended from here (#215: the actions are in the row's ⋯ menu)
  const mine = s.getByRole("row", { name: /you, this session/ });
  if (await mine.getByRole("button", { name: /^Actions for/ }).count()) {
    await mine.getByRole("button", { name: /^Actions for/ }).click();
    await expect(page.getByRole("menu")).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "End session" })).toHaveCount(0);
    await page.keyboard.press("Escape");
  }
  // #128: the diagnostics download
  await aboutTab(page, "System health");
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download diagnostics" }).click();
  expect((await dl).suggestedFilename()).toMatch(/^pennywarden-diagnostics-\d{14}\.json$/);
  // #129: health and the integrity check
  const h = page.getByRole("region", { name: "Health" });
  await expect(h.getByText("up to date")).toBeVisible();
  await h.getByRole("button", { name: "Run integrity check" }).click();
  await expect(h.getByRole("status")).toContainText("The database passed the integrity check.");
});

test("#130: maintenance mode - Administrators keep working, the others see the message and can't change anything", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "Advanced");
  const p = page.getByRole("region", { name: "Maintenance mode" });
  await p.getByLabel("Message for the users").fill("Year-end close until Monday.");
  await p.getByRole("button", { name: "Turn on maintenance mode" }).click();
  await expect(page.getByTestId("maintenance-notice").first()).toContainText("Year-end close until Monday.");
  await logout(page);
  await expect(page.getByTestId("maintenance-notice")).toContainText("Year-end close until Monday.");   // sign-in page
  await login(page, "bm1");
  await expect(page.getByTestId("maintenance-notice")).toContainText("changes are paused");
  const csrf = (await (await page.request.get("/api/auth/me")).json()).csrf_token;
  const r = await page.request.post("/api/entities", { data: { entity_type: "ORGANIZATION", organization_name: "Blocked Org", confirmations: ["DUPLICATE_ENTITY"] }, headers: { "X-CSRF-Token": csrf } });
  expect(r.status()).toBe(503);
  // build 13: no screen offers an action that would change something (they see what a read-only role sees)
  const shown = await pausedActions(page, ["/", "/fiscal-years", "/budgets", "/bank-accounts", "/register?account=1", "/entities",
                                           "/fundraisers", "/notifications", "/reports"]);
  expect(shown).toEqual([]);
  // looking things up still works, also when it is a POST (the Financial Flow Report review)
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  await logout(page);
  await login(page, "ru1", "Brand-New-Pass-99");
  expect(await pausedActions(page, ["/", "/register?account=1", "/payments", "/entities", "/notifications"])).toEqual([]);
  await logout(page);
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "Advanced");
  await page.getByRole("region", { name: "Maintenance mode" }).getByRole("button", { name: "Turn off" }).click();
  await expect(page.getByTestId("maintenance-notice")).toHaveCount(0);
});

test("#134: real names - search the Users list, sort by last name, names in the audit log", async ({ page }) => {
  await login(page, "admin");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await nav.getByRole("link", { name: "Users", exact: true }).click();
  await page.getByLabel("Search users").fill("manager");
  await expect(page.getByRole("row", { name: /bm1/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /ru1/ })).toHaveCount(0);
  await page.getByLabel("Search users").fill("");
  await page.getByLabel("Sort by last name").check();
  await nav.getByRole("link", { name: "Audit Log", exact: true }).click();
  await expect(page.getByRole("cell", { name: "Pat Example - admin" }).first()).toBeVisible();
});

test("#133: readable audit log - summary, what changed, technical details", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Audit Log", exact: true }).click();
  // (the "Object type" label's text also contains "…transaction", so find the Action field by its exact label)
  await page.locator(".filters .field").filter({ has: page.locator(".field-label", { hasText: /^Action$/ }) }).locator("select")
    .selectOption({ label: "User created" });
  const row = page.getByRole("row", { name: /User created/ }).first();
  await row.getByRole("button", { name: "Details" }).click();
  const detail = page.locator(".audit-readable").first();
  await expect(detail.getByRole("table", { name: "What changed" })).toBeVisible();
  await expect(detail.getByRole("rowheader", { name: "Username" })).toBeVisible();
  await expect(detail.locator("details.technical pre").first()).toBeHidden();
  await detail.getByText("Show technical details").click();
  await expect(detail.locator("details.technical pre").first()).toBeVisible();
});

test("#131: the security overview lists what needs attention", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "System/About", exact: true }).click();
  await aboutTab(page, "Security");
  const ov = page.getByRole("region", { name: "Security overview" });
  await expect(ov.getByTestId("secov-two_step")).toContainText("Needs attention");
  await expect(ov.getByTestId("secov-admins")).toContainText("Info");
});

// ---------------------------------------------------------------- 2.0.0 build 11 (#217): several templates, Duplicate, window envelopes
test("#217: several cover letters and envelopes, Duplicate, the window-envelope pointer and picture previews", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "Payments Setup" }).click();
  const letters = page.getByRole("region", { name: "Cover letters" });
  const envelopes = page.getByRole("region", { name: "Envelopes" });
  await expect(letters.getByRole("row", { name: /Invoice payment letter/ }).first()).toBeVisible();   // the list has loaded
  const before = await letters.getByRole("row").count();
  // a second cover letter gets a free name, selected so it can be typed over at once
  await letters.getByRole("button", { name: "New cover letter" }).click();
  await expect(page.getByRole("heading", { name: /^Cover letter: Invoice payment letter \d+$/ })).toBeVisible();
  const nameBox = page.getByLabel("Name", { exact: true });
  await expect(nameBox).toBeFocused();
  await page.keyboard.type("Refund letter");
  await expect(nameBox).toHaveValue("Refund letter");
  // the preview is a picture of the printed page (Safari shows inline PDFs blank)
  const pic = page.getByRole("img", { name: "Cover letter preview" });
  await expect(pic).toBeVisible();
  await expect.poll(() => pic.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0 && i.naturalHeight > i.naturalWidth)).toBe(true);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  await expect(letters.getByRole("row")).toHaveCount(before + 1);
  // Duplicate copies a template and opens the copy with its name selected
  await rowAction(letters, "Refund letter", "Duplicate");
  await expect(page.getByRole("heading", { name: "Cover letter: Refund letter copy" })).toBeVisible();
  await expect(page.getByLabel("Name", { exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  await expect(letters.getByRole("row", { name: /Refund letter copy/ })).toBeVisible();
  // build 13: a new letter left without saving leaves nothing behind
  const kept = await letters.getByRole("row").count();
  await letters.getByRole("button", { name: "New cover letter" }).click();
  await expect(page.getByTestId("draft-note")).toBeVisible();
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();      // untouched: no question asked
  await expect(letters.getByRole("row")).toHaveCount(kept);
  await letters.getByRole("button", { name: "New cover letter" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Changed but not kept");
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  await expect(letters.getByRole("row")).toHaveCount(kept);
  await expect(letters.getByRole("row", { name: /Changed but not kept/ })).toHaveCount(0);
  // a window-envelope letter from the preset
  await letters.getByRole("button", { name: "New window-envelope letter" }).click();
  await expect(page.getByRole("heading", { name: "Cover letter: Window envelope letter" })).toBeVisible();
  await expect(page.getByLabel("Address for a window envelope")).toHaveValue("LETTER");
  await expect(page.getByLabel("Print fold marks")).toHaveValue("FRONT");          // #247: on for new window letters
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  // the Envelopes section points to the cover letter's Window envelope settings
  const pointer = envelopes.getByTestId("window-pointer");
  await expect(pointer).toContainText("Using #10 double-window envelopes?");
  await pointer.getByRole("button", { name: /Open the window envelope settings of/ }).click();
  await expect(page.getByRole("heading", { name: "Cover letter: Window envelope letter" })).toBeVisible();
  await expect(page.getByLabel("Address for a window envelope")).toBeFocused();
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  // a second envelope, its picture preview, and the same pointer inside the envelope editor
  await envelopes.getByRole("button", { name: "New #10 envelope" }).click();
  await expect(page.getByRole("heading", { name: /^Envelope: #10 envelope \d+$/ })).toBeVisible();
  const env = page.getByRole("img", { name: "Envelope preview" });
  await expect.poll(() => env.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 2 * i.naturalHeight)).toBe(true);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.getByTestId("window-pointer").getByRole("button", { name: /Open the window envelope settings of/ }).click();
  await expect(page.getByLabel("Address for a window envelope")).toBeFocused();
  await page.getByRole("button", { name: "Back to Payments Setup" }).click();
  await expect(envelopes.getByRole("row", { name: /#10 envelope \d+/ })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/light-check-templates.png", fullPage: true });
});

// ---------------------------------------------------------------- 2.0.0 build 11 (#215): row actions in a menu
test("#215: Edit stays visible; the other row actions are in a keyboard-usable ⋯ menu", async ({ page }) => {
  await login(page, "admin");
  await page.goto("/users");
  const row = page.getByRole("row", { name: /bm1/ });
  await expect(row.getByRole("button", { name: "Edit", exact: true })).toBeVisible();
  await expect(row.getByRole("button", { name: "Reset password" })).toHaveCount(0);      // no longer on the row
  const btn = row.getByRole("button", { name: "Actions for bm1" });
  await expect(btn).toHaveAttribute("aria-haspopup", "menu");
  await expect(btn).toHaveAttribute("title", "Actions for bm1");
  await expect(btn).toHaveAttribute("aria-expanded", "false");
  expect(await btn.evaluate((b) => b.tagName)).toBe("BUTTON");
  // keyboard: Enter opens on the first item, arrows move, Escape closes and returns the focus to the button
  await btn.focus();
  await page.keyboard.press("Enter");
  const menu = page.getByRole("menu", { name: "Actions for bm1" });
  await expect(menu).toBeVisible();
  await expect(btn).toHaveAttribute("aria-expanded", "true");
  await expect(menu.getByRole("menuitem").first()).toBeFocused();
  await expect(menu.getByRole("menuitem", { name: "Reset password" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByRole("menuitem").nth(1)).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");                                                   // wraps to the last item
  await expect(menu.getByRole("menuitem").last()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(btn).toBeFocused();
  // ArrowUp on the button opens on the last item; Space chooses it; a dialog opens
  await page.keyboard.press("ArrowUp");
  await expect(page.getByRole("menu").getByRole("menuitem").last()).toBeFocused();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Space");
  await expect(page.getByRole("menu").getByRole("menuitem", { name: "Reset password" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).first().click();
  // clicking outside closes it
  await btn.click();
  await expect(page.getByRole("menu")).toBeVisible();
  await page.getByRole("heading", { name: "Users" }).first().click();
  await expect(page.getByRole("menu")).toHaveCount(0);
  // every row of the users table: Edit plus the menu button
  for (const r of await page.locator("table tbody tr").all()) {
    await expect(r.getByRole("button", { name: "Edit", exact: true })).toHaveCount(1);
    await expect(r.getByRole("button", { name: /^Actions for / })).toHaveCount(1);
  }
  await page.screenshot({ path: "e2e-screenshots/light-row-menu.png" });
});

// ---------------------------------------------------------------- 2.0.0 build 11 (#216): System/About in tabs
test("#216: System/About tabs have their own addresses; Auditors see three; banners open the right tab", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  const tabs = page.getByRole("tablist", { name: "System/About sections" });
  await expect(tabs.getByRole("tab")).toHaveText(["About", "General", "Branding", "Settings", "Backups", "Security", "System health", "Advanced"]);
  await expect(page).toHaveURL(/\/about$/);
  await expect(tabs.getByRole("tab", { name: "About" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel")).toContainText("Data protection");
  // each tab opens at its own address; reloading keeps it; Back returns to the previous tab
  await aboutTab(page, "Backups");
  await expect(page).toHaveURL(/\/about\/backups$/);
  await expect(page.getByRole("heading", { name: "Backup / Restore" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Optional modules" })).toHaveCount(0);   // only this tab's sections
  await page.reload();
  await expect(tabs.getByRole("tab", { name: "Backups" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Backup / Restore" })).toBeVisible();
  await aboutTab(page, "System health");
  await expect(page).toHaveURL(/\/about\/health$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/about\/backups$/);
  await expect(tabs.getByRole("tab", { name: "Backups" })).toHaveAttribute("aria-selected", "true");
  // keyboard: arrows move between the tabs and open them
  await tabs.getByRole("tab", { name: "Backups" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "Security" })).toBeFocused();
  await expect(page).toHaveURL(/\/about\/security$/);
  await page.keyboard.press("Home");
  await expect(page).toHaveURL(/\/about$/);
  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(/\/about\/advanced$/);
  // a bookmarked address opens its tab directly; an unknown one shows About
  await page.goto("/about/general");
  await expect(page.getByLabel("Organization name")).toBeVisible();
  await page.goto("/about/nonsense");
  await expect(page).toHaveURL(/\/about$/);
  // the backup and disk-space banners link to their tab
  await page.route("**/api/system/backup-schedule/alert", (r) => r.fulfill({ json: {
    failed: true, message: "The last scheduled backup failed.", stale: false, low_disk: true, low_disk_message: "Low disk space." } }));
  await page.goto("/");
  await page.getByTestId("backup-failed-banner").getByRole("link", { name: "Backup settings" }).click();
  await expect(page).toHaveURL(/\/about\/backups$/);
  await expect(page.getByRole("heading", { name: "Backup / Restore" })).toBeVisible();
  await page.getByTestId("low-disk-banner").getByRole("link", { name: "System health" }).click();
  await expect(page).toHaveURL(/\/about\/health$/);
  await expect(page.getByRole("region", { name: "Health" })).toBeVisible();
  await page.unroute("**/api/system/backup-schedule/alert");
  await page.screenshot({ path: "e2e-screenshots/light-about-tabs.png" });
  // an Auditor sees About, General (2.2.0, #349), Settings and Security only; an Administrator-only address shows About
  await createUser(page, "auditor1", "Auditor");
  await logout(page);
  await login(page, "auditor1");
  await page.getByRole("link", { name: "System/About" }).click();
  await expect(page.getByRole("tablist", { name: "System/About sections" }).getByRole("tab")).toHaveText(["About", "General", "Settings", "Security"]);
  await page.goto("/about/backups");
  await expect(page).toHaveURL(/\/about$/);
  await page.goto("/about/security");
  await expect(page.getByRole("region", { name: "Security overview" })).toBeVisible();
  await logout(page);
});

test("2.2.0 (#349): a financial user sees System/About read-only - About and General only", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "System/About" }).click();
  await expect(page.getByRole("tablist", { name: "System/About sections" }).getByRole("tab")).toHaveText(["About", "General"]);
  const panel = page.getByRole("tabpanel");
  await expect(panel).toContainText("Version");
  await expect(panel).not.toContainText("Data protection");
  await expect(panel).not.toContainText("Bind address");
  await expect(page.getByTestId("update-check-status")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Check now" })).toHaveCount(0);
  await expect(panel.getByRole("checkbox")).toHaveCount(0);
  await page.getByRole("tab", { name: "General" }).click();
  await expect(page).toHaveURL(/\/about\/general$/);
  await expect(page.getByTestId("org-view")).toContainText("Organization name");
  await expect(page.getByRole("tabpanel").getByRole("textbox")).toHaveCount(0);
  await expect(page.getByRole("tabpanel").getByRole("button", { name: "Save" })).toHaveCount(0);
  const mods = page.getByTestId("modules-status");
  await expect(mods.getByRole("row", { name: /Payments/ })).toContainText("Register Users");
  await expect(mods.getByRole("row", { name: /Fundraisers/ })).toContainText(/Enabled|Disabled/);
  await page.screenshot({ path: "e2e-screenshots/light-about-financial.png" });
  // Administrator-only tab addresses fall back to /about
  for (const t of ["settings", "backups", "security", "health", "advanced", "branding"]) {
    await page.goto(`/about/${t}`);
    await expect(page).toHaveURL(/\/about$/);
  }
  await logout(page);
});

// ---------------------------------------------------------------- 2.0.0 build 12 (#188): audit log export
test("#188: an Auditor exports the filtered, readable audit log as CSV and a printable PDF; the export is recorded", async ({ page }) => {
  await login(page, "auditor1");      // created by the #216 test
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Audit Log", exact: true }).click();
  // what the screen shows is taken from the filtered list's own response: right after the change the page may still
  // show the unfiltered list for a moment, and reading it then raced on fast runners (develop build 149)
  const filtered = page.waitForResponse((r) => r.url().includes("/api/audit-events?") && r.url().includes("category=BUSINESS"));
  await page.locator(".filters .field").filter({ has: page.locator(".field-label", { hasText: /^Category$/ }) }).locator("select").selectOption("BUSINESS");
  const listed = await (await filtered).json();
  const total: number = listed.total;
  await expect(page.locator(".pager span")).toHaveText(new RegExp(` of ${total}$`));   // exact: " of 159" is also in " of 1593"
  const firstSummary: string = listed.items[0].readable.summary.split(" — ").slice(1).join(" — ");
  await expect(page.locator(".audit-table tbody tr").first().locator("td").nth(2).locator(".muted")).toHaveText(firstSummary);
  // CSV: downloaded at once, one row per matching entry (all pages), same summaries as the screen
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await dl;
  expect(file.suggestedFilename()).toMatch(/^audit-log-\d{8}-\d{6}\.csv$/);
  const { readFileSync } = await import("node:fs");
  const csv = readFileSync((await file.path())!, "utf-8");
  expect(csv.split("\n")[0]).toContain("Event #,Local time (");
  expect(csv).toContain(firstSummary.replace(/"/g, '""'));
  // one row per entry: a row starts with the event # and its local time (a multi-line cell can't look like that)
  expect((csv.match(/^\d+,\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} /gm) || []).length).toBe(total);
  // PDF: shown with Print, Open in a new tab and Download
  await page.getByRole("button", { name: "Printable PDF" }).click();
  const v = page.getByRole("dialog", { name: "Audit log export" });
  await expect(v.getByRole("button", { name: "Print…" })).toBeVisible();
  await expect(v.getByRole("link", { name: "Download PDF" })).toHaveAttribute("download", /^audit-log-\d{8}-\d{6}\.pdf$/);
  await v.getByRole("button", { name: "Close" }).first().click();
  // both exports are in the log (Security category)
  await page.locator(".filters .field").filter({ has: page.locator(".field-label", { hasText: /^Category$/ }) }).locator("select").selectOption("SECURITY");
  await expect(page.locator(".audit-action", { hasText: "Audit log exported" })).toHaveCount(2);
  await logout(page);
});

// ---------------------------------------------------------------- 2.0.0 build 11 (#214): UI standards (docs/ui-standards.md)
/** Measures every visible form row (.row, .filters, .page-head, .report-options with fields) on the page: per line of the
 * row, the inputs and selects share one top and the standard height, full-size buttons match them, and small buttons
 * and inline checkboxes are centred on them. Returns the violations as readable strings. */
async function layoutViolations(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const H = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--control-h")) || 34;
    const vis = (e: Element) => { const r = (e as HTMLElement).getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden"; };
    const name = (e: Element) => (e.closest(".field")?.querySelector(".field-label, label")?.textContent || (e as HTMLElement).innerText || e.getAttribute("aria-label") || e.tagName).trim().slice(0, 40);
    for (const row of Array.from(document.querySelectorAll(".row, .filters, .page-head, .report-options"))) {
      if (!vis(row)) continue;
      const kids = Array.from(row.children).flatMap((c) => (c.matches("fieldset.form-guard") ? Array.from(c.children) : [c])).filter(vis);
      const fields = kids.filter((k) => k.matches(".field"));
      if (!fields.length) continue;
      const ctrls = fields.map((f) => f.querySelector("input:not([type=checkbox]):not([type=radio]):not([type=file]), select"))
        .filter((c): c is HTMLElement => !!c && vis(c));
      const where = `${(row.closest("section, .modal, form, main")?.querySelector("h1, h2, h3")?.textContent || "").trim().slice(0, 40)} / ${ctrls.map(name).join(", ")}`;
      // lines of a wrapped row: controls whose tops are within 6px
      const lines: HTMLElement[][] = [];
      for (const c of ctrls) {
        const t = c.getBoundingClientRect().top;
        const line = lines.find((l) => Math.abs(l[0].getBoundingClientRect().top - t) < 6);
        if (line) line.push(c); else lines.push([c]);
      }
      for (const line of lines) {
        const r0 = line[0].getBoundingClientRect();
        for (const c of line) {
          const r = c.getBoundingClientRect();
          if (Math.abs(r.top - r0.top) > 1) out.push(`${where}: "${name(c)}" is ${Math.round(r.top - r0.top)}px off the line`);
          if (Math.abs(r.height - H) > 1) out.push(`${where}: "${name(c)}" is ${Math.round(r.height)}px tall, not ${H}`);
        }
        const mid = r0.top + r0.height / 2;
        for (const k of kids) {
          if (!k.matches("button, a.button, label.button, .check")) continue;
          const r = k.getBoundingClientRect();
          if (r.bottom < r0.top - 4 || r.top > r0.bottom + 4) continue;           // on another line of the row
          const small = k.matches("button.small, a.button.small, label.button");
          if (k.matches(".check") || small) {
            if (Math.abs(r.top + r.height / 2 - mid) > 1.5) out.push(`${where}: "${name(k)}" is not centred on the inputs (${Math.round(r.top + r.height / 2 - mid)}px)`);
          } else if (Math.abs(r.top - r0.top) > 1 || Math.abs(r.height - H) > 1) {
            out.push(`${where}: button "${name(k)}" is not on the input line (top ${Math.round(r.top - r0.top)}px, ${Math.round(r.height)}px tall)`);
          }
        }
      }
    }
    return out;
  });
}

async function formCheck(page: Page, shot: string) {
  await page.waitForTimeout(150);
  await page.screenshot({ path: `e2e-screenshots/forms/${shot}.png`, fullPage: true });
  expect(await layoutViolations(page), shot).toEqual([]);
  // build 13: only the content area scrolls - the page itself never runs on past the end (a long editor did)
  expect(await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight), `${shot}: the page scrolls`).toBeLessThanOrEqual(1);
}

test("#230: in Safari the check and test-print previews are pictures of the PDF, and Print… opens the PDF in a new tab", async ({ browser }) => {
  // Safari draws a PDF in an inline frame blank; Chromium with Safari's user agent takes the same path in the app
  const ctx = await browser.newContext({ baseURL: "http://127.0.0.1:8798",
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15" });
  const page = await ctx.newPage();
  await login(page, "ru1", "Brand-New-Pass-99");
  const post = await apiAs(page);
  const ents = await (await page.request.get("/api/entities?search=Sample%20Supply")).json();
  const ent = (ents.items || ents).find((e: any) => /Sample Supply Company/.test(e.display_name || e.organization_name || ""));
  const opts = await (await page.request.get("/api/budgets/selectable?fiscal_year_id=1&transaction_type=WITHDRAWAL")).json();
  const tr = await post("/api/transactions", { bank_account_id: 1, transaction_type: "WITHDRAWAL", transaction_date: "2026-11-27",
    entity_id: ent.id, check_number: "8391", allocations: [{ budget_id: opts.find((o: any) => o.label === "1000-01 Travel").id, amount: "42.00", invoice_number: "S-1", description: "Safari check" }] });
  expect(tr.status(), await tr.text()).toBe(201);
  const t = await tr.json();
  await page.goto(`/register?account=1&txn=${t.id}`);
  await expect(page.locator(`#txn-${t.id}`).getByRole("button", { name: `Details for transaction ${t.id}` })).toHaveAttribute("aria-expanded", "true");
  // build 13: a new payment starts on Payments only - the register has Create payment… on a withdrawal, no New payment
  await expect(page.getByRole("button", { name: "New transaction" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New payment" })).toHaveCount(0);
  await page.getByRole("button", { name: "Create payment…" }).click();
  const dlg = page.getByRole("dialog", { name: `Print check – transaction #${t.id}` });
  // the plain-paper test: a picture, no PDF frame
  await dlg.getByRole("button", { name: "Test print on plain paper" }).click();
  const test = page.getByRole("dialog", { name: "Alignment test (plain paper)" });
  await expect(test.getByTestId("pdf-picture")).toBeVisible();
  expect(await test.getByTestId("pdf-picture").evaluate((i: HTMLImageElement) => i.naturalWidth)).toBeGreaterThan(500);
  await expect(test.locator("iframe")).toHaveCount(0);
  await expect(test.getByTestId("safari-print-note")).toBeVisible();
  // Print… opens the PDF (a blob: link) in a new tab; the headless browser on GitHub's runners has no PDF viewer, so the
  // tab may never show an address there - that the tab opens from the PDF's link is what is checked
  await page.evaluate(() => {
    const orig = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
      HTMLAnchorElement.prototype.click = orig;
      (window as any).__opened = `${this.target} ${this.href}`;
      orig.call(this);
    };
  });
  const [tab] = await Promise.all([ctx.waitForEvent("page"), test.getByRole("button", { name: "Print…" }).click()]);
  expect(await page.evaluate(() => (window as any).__opened)).toMatch(/^_blank blob:/);
  await tab.close();
  await test.getByRole("button", { name: "Close" }).first().click();
  // the check itself
  await dlg.getByLabel("Type the number printed on the check that is in the printer").fill("8391");
  await dlg.getByRole("button", { name: "Print check" }).click();
  const chk = page.getByRole("dialog", { name: "Check #8391" });
  await expect(chk.getByTestId("pdf-picture")).toBeVisible();
  await expect(chk.locator("iframe")).toHaveCount(0);
  await chk.getByRole("button", { name: "Close" }).first().click();
  await expect(dlg.getByText("Check #8391 is ready.")).toBeVisible();
  await dlg.getByRole("button", { name: "Yes – done" }).click();
  // printed: the register offers Reprint check or letter…; the dialog has two closed sections (letter templates exist
  // since the #165 test) - the letter or envelope can be printed again without touching the check
  await expect(page.getByRole("button", { name: "Reprint check or letter…" })).toBeVisible();   // in the open details row
  await page.getByRole("button", { name: "Reprint check or letter…" }).click();
  const re = page.getByRole("dialog", { name: `Print check – transaction #${t.id}` });
  await expect(re.getByText("Check #8391 was already printed. What do you need to print again?")).toBeVisible();
  const reCheck = re.getByTestId("reprint-check"), reLetter = re.getByTestId("reprint-letter");
  await expect(reCheck).not.toHaveAttribute("open", "");
  await expect(reLetter).not.toHaveAttribute("open", "");
  await expect(re.getByLabel("Reason for the reprint (required)")).toHaveCount(0);
  await reLetter.getByText("Reprint the letter or envelope").click();
  await expect(reLetter.getByText("The check is not printed again.")).toBeVisible();
  await expect(reLetter.getByRole("button", { name: /Print envelope/ })).toBeVisible();
  // another letter template can be chosen; a window-envelope letter needs no envelope (it can still be printed), and
  // going back to a standard letter brings the envelope back
  const include = reLetter.getByRole("checkbox", { name: "Include cover letter" });
  if (!(await include.isChecked())) await include.check();
  const letterSel = reLetter.getByRole("combobox", { name: "Cover letter", exact: true });
  const standard = await letterSel.inputValue();
  await letterSel.selectOption({ label: "Window envelope letter" });
  await expect(reLetter.getByTestId("window-letter-note")).toContainText("no envelope to print");
  await expect(reLetter.getByRole("button", { name: /Print envelope/ })).toHaveCount(0);
  await letterSel.selectOption(standard);
  await expect(reLetter.getByTestId("window-letter-note")).toHaveCount(0);
  await expect(reLetter.getByRole("button", { name: /Print envelope/ })).toBeVisible();
  await expect(re.getByLabel("Reason for the reprint (required)")).toHaveCount(0);
  await reCheck.getByText("Reprint the check").click();
  await expect(reCheck.getByLabel("Reason for the reprint (required)")).toBeVisible();
  await re.getByRole("button", { name: "Close" }).first().click();
  await ctx.close();
});

test("#214: form rows line up - one control height, buttons and checkboxes centred, solid action bar (every form)", async ({ page }) => {
  test.setTimeout(180_000);
  // Budget Manager screens
  await login(page, "bm1");
  for (const [path, shot] of [["/fiscal-years", "fiscal-years"], ["/budgets", "budgets"], ["/bank-accounts", "bank-accounts"],
                              ["/entities", "entities"], ["/reports", "reports"], ["/register", "register-bm"], ["/", "dashboard"]] as const) {
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    await formCheck(page, shot);
  }
  await page.goto("/entities");
  await page.getByRole("button", { name: "New entity" }).click();
  await formCheck(page, "entity-new");
  await page.goto("/bank-accounts");
  await page.getByRole("button", { name: /New (bank )?account/ }).first().click();
  await formCheck(page, "bank-account-new");
  await page.goto("/");
  await logout(page);
  // Register User: the register's filters and transaction form, a new payment
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.goto("/register?account=1");
  await expect(page.getByLabel("Register Fiscal Year filter")).toBeVisible();
  await formCheck(page, "register");
  await page.getByRole("button", { name: /New transaction/ }).first().click();
  await formCheck(page, "register-new-transaction");
  await page.goto("/payments");
  await page.getByRole("link", { name: /New payment/ }).or(page.getByRole("button", { name: /New payment/ })).first().click();
  await expect(page.getByLabel("Check #")).toBeVisible();
  await formCheck(page, "payment-new");
  await page.goto("/");
  await logout(page);
  // Administrator: users, audit log, Payments Setup and its editors, System/About, My account
  await login(page, "admin");
  for (const [path, shot] of [["/users", "users"], ["/audit-log", "audit-log"], ["/check-setup", "payments-setup"], ["/about", "about"],
                              ["/about/general", "about-general"], ["/about/settings", "about-settings"], ["/about/backups", "about-backups"],
                              ["/about/security", "about-security"], ["/about/health", "about-health"], ["/about/advanced", "about-advanced"],
                              ["/account", "account"]] as const) {
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    await formCheck(page, shot);
  }
  await page.goto("/users");
  await page.getByRole("button", { name: "New user" }).click();
  await formCheck(page, "user-new");
  await page.goto("/");
  await page.goto("/check-setup");
  for (const [region, shot] of [["Check styles", "check-style-editor"], ["Cover letters", "letter-editor"], ["Envelopes", "envelope-editor"]] as const) {
    await page.getByRole("region", { name: region }).getByRole("button", { name: "Edit", exact: true }).first().click();
    const back = page.getByRole("button", { name: /^Back to (Payments Setup|check styles)$/ });
    await expect(back).toBeVisible();
    await formCheck(page, shot);
    // the action bar is a solid footer: whatever is under the bottom edge of the content area is the bar
    await page.locator(".content").evaluate((c) => { c.scrollTop = c.scrollHeight / 3; });
    await page.waitForTimeout(100);
    const covered = await page.evaluate(() => {
      const c = document.querySelector(".content")!.getBoundingClientRect();
      const bar = document.querySelector(".sticky-actions")!;
      return [c.left + 4, c.left + c.width / 2, c.right - 24].every((x) => [c.bottom - 2, c.bottom - 12].every((y) => {
        const e = document.elementFromPoint(x, y);
        return !!e && (e === bar || bar.contains(e));
      }));
    });
    expect(covered, `${shot}: content shows through or beside the action bar`).toBe(true);
    expect(await page.locator(".sticky-actions").evaluate((b) => getComputedStyle(b).backgroundColor)).not.toMatch(/rgba\(.*, 0\)|transparent/);
    await back.click();
  }
});

// Keep this test LAST: it removes the financial data the other tests use.
test("#312: Donations module - Administrator sets up the receipt; a Register User marks a deposit's donations and prints receipts (duplicate, corrected); an Auditor sees them", async ({ page }) => {
  test.setTimeout(180_000);   // three sign-ins and five printed PDFs
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "General");
  await page.getByLabel("Donations module").check();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await page.reload();
  await page.getByRole("link", { name: "Donations Setup" }).click();
  // 2.1.0 (#314): the EIN and address come from the organization profile (entered in the #126 test)
  await expect(page.getByTestId("setup-missing")).toHaveCount(0);
  await expect(page.getByTestId("donation-org")).toContainText("12-3456789");
  await expect(page.getByTestId("donation-org")).toContainText("Sampletown, US 55555");
  await expect(page.getByLabel("Include EIN on receipts")).toBeChecked();   // 2.3.0 (#393): on by default
  await expect(page.getByRole("img", { name: "Donation receipt preview" })).toBeVisible();
  // 2.3.0 (#395): the signer comes from the shared Signers page, tagged for donation letters
  await expect(page.getByText("No signers are tagged for donation letters yet")).toBeVisible();
  await page.goto("/signers");
  await page.getByRole("button", { name: "Add signer…" }).click();
  const sd = page.getByRole("dialog", { name: "Add signer" });
  await sd.getByLabel(/^Name/).fill("Riley Sample");
  await sd.getByLabel("Title (optional)").fill("Treasurer");
  await expect(sd.getByLabel("Donation receipts and statements")).toBeChecked();
  await sd.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("row", { name: /Riley Sample/ })).toContainText("Donation receipts and statements");
  await page.goto("/donation-setup");
  await page.getByTestId("rc-signer").selectOption({ label: "Riley Sample (Treasurer)" });
  await page.getByTestId("rc-signature-mode").selectOption("SPACE");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await expect(page.getByTestId("setup-missing")).toHaveCount(0);
  await page.getByRole("button", { name: "Test print (sample data)" }).click();
  const tp = page.getByRole("dialog", { name: "Donation receipt test print" });
  await expect(tp.getByRole("button", { name: "Print…" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/light-donation-setup.png", fullPage: true });
  await tp.getByRole("button", { name: "Close" }).first().click();
  await logout(page);

  // Register User: a deposit from two made-up donors
  await login(page, "ru1", "Brand-New-Pass-99");
  // 2.1.0 (#314): the organization is an entity too, maintained in System/About
  await page.goto("/entities");
  await expect(page.getByRole("row", { name: /E2E Org/ }).getByTestId("org-badge")).toBeVisible();
  await expect(page.getByRole("row", { name: /E2E Org/ })).toContainText("System/About");
  const post = await apiAs(page);
  const today = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  const accts = (await (await page.request.get("/api/bank-accounts")).json()).filter((a: any) => a.register_enabled && a.status === "ACTIVE");
  const nat = await (await page.request.get(`/api/fiscal-years/natural?date=${today}`)).json();
  const dep = await (await page.request.get(`/api/budgets/selectable?fiscal_year_id=${nat.default_fiscal_year_id}&transaction_type=DEPOSIT`)).json();
  const donors = [];
  for (const n of ["Sample Donor Alpha", "Sample Donor Beta"]) {
    const r = await post("/api/entities", { entity_type: "INDIVIDUAL", primary_contact: n, address_line1: "1 Example Lane", city: "Sampletown", state_region: "US", postal_code: "55555", confirmations: ["DUPLICATE_ENTITY"] });
    expect(r.status()).toBe(201);
    donors.push(await r.json());
  }
  let body: any = { bank_account_id: accts[0].id, transaction_type: "DEPOSIT", transaction_date: today, no_attachment: true, no_attachment_reason: "e2e",
    allocations: [{ budget_id: dep[0].id, amount: "100.00", entity_id: donors[0].id, description: "Gift" },
                  { budget_id: dep[0].id, amount: "40.00", entity_id: donors[0].id, description: "Raffle tickets" },
                  { budget_id: dep[0].id, amount: "75.00", entity_id: donors[1].id, description: "Gift" }] };
  let r = await post("/api/transactions", body);
  if (r.status() === 409) { body = { ...body, confirmations: ((await r.json()).error.warnings || []).map((w: any) => w.code) }; r = await post("/api/transactions", body); }
  expect(r.status(), await r.text()).toBe(201);
  const t = await r.json();
  await page.goto(`/register?account=${accts[0].id}&txn=${t.id}`);
  await page.getByRole("button", { name: "Donation receipt…" }).click();
  const dlg = page.getByRole("dialog", { name: `Donation receipt – deposit #${t.id}` });
  await expect(dlg.getByText("No line is marked as a donation yet.")).toBeVisible();
  // one donor: ticking the line shows the donor's block at once (no save), then Details, then Preview / Print at the bottom
  await dlg.getByLabel("Donation: Sample Donor Alpha $100.00").check();
  await dlg.getByLabel("Purpose").first().fill("Building fund");
  const alpha = dlg.getByRole("group", { name: "Donor Sample Donor Alpha" });
  await expect(alpha).toContainText("$100.00");
  await expect(alpha).toContainText("Not printed");
  // {DETAILS} is in the default receipt letter: a write-up for this donor, with a variable
  await dlg.getByLabel("Details for Sample Donor Alpha (optional)").fill("Your gift of ${AMOUNT} will buy new flags.");
  await expect(dlg.getByText("Unsaved changes (Print saves them first)")).toBeVisible();
  // Preview (Kyle, 2026-10-23): the receipt as it would print, from the screen, watermarked; nothing is saved
  await dlg.getByRole("button", { name: "Preview" }).click();
  const prev = page.getByRole("dialog", { name: "Preview – Sample Donor Alpha" });
  await expect(prev.getByRole("button", { name: "Print…" })).toBeVisible();
  await expect(prev.getByTestId("preview-note")).toContainText("Nothing is saved");
  await page.screenshot({ path: "e2e-screenshots/light-donation-preview.png" });
  await prev.getByRole("button", { name: "Close" }).first().click();
  await expect(alpha).toContainText("Not printed");
  await expect(dlg.getByText("Unsaved changes (Print saves them first)")).toBeVisible();
  // Print saves first: one click
  await dlg.getByRole("button", { name: "Print receipt" }).click();
  const pv = page.getByRole("dialog", { name: "Donation receipt – Sample Donor Alpha" });
  await expect(pv.getByRole("button", { name: "Print…" })).toBeVisible();
  await pv.getByRole("button", { name: "Close" }).first().click();
  await expect(alpha).toContainText("R-2026-0001");
  await expect(dlg.getByRole("button", { name: "Print duplicate" })).toBeVisible();
  // a second donor, received before the deposit (Kyle, 2026-10-22): each donor's block has its own Preview / Print
  await dlg.getByLabel("Donation: Sample Donor Beta $75.00").check();
  const earlier = new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10);
  await dlg.getByLabel("Date received: Sample Donor Beta $75.00").fill(earlier);
  const beta = dlg.getByRole("group", { name: "Donor Sample Donor Beta" });
  await expect(beta).toContainText(earlier);
  await dlg.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dlg.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await expect(alpha.getByRole("button", { name: "Preview" })).toBeVisible();
  await alpha.getByRole("button", { name: "Print duplicate" }).click();
  await pv.getByRole("button", { name: "Close" }).first().click();
  // the raffle tickets were a donation too: the amount changes, so the next receipt is a corrected one
  await dlg.getByLabel("Donation: Sample Donor Alpha $40.00").check();
  await dlg.getByLabel("Goods or services value").nth(1).fill("10.00");
  await dlg.getByLabel("Goods or services description").fill("Raffle prize drawing");
  await expect(alpha).toContainText("$140.00");
  await dlg.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dlg.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await alpha.getByRole("button", { name: "Print corrected receipt" }).click();
  const conf = page.getByRole("dialog", { name: "Confirmation required" });
  await expect(conf).toContainText("Print a corrected receipt");
  await conf.getByLabel("I have reviewed these warnings and explicitly confirm.").check();
  await conf.getByRole("button", { name: "Confirm and continue" }).click();
  await pv.getByRole("button", { name: "Close" }).first().click();
  await dlg.getByText(/^Printed receipts/).click();               // collapsed history at the top
  const printed = dlg.getByTestId("donation-receipts");
  await expect(printed.getByRole("row")).toHaveCount(4);
  await expect(printed.getByRole("row", { name: /Corrected/ })).toContainText("In force");
  await expect(printed.getByRole("row", { name: /Duplicate/ })).toContainText("Replaced");
  await page.screenshot({ path: "e2e-screenshots/light-donation-receipt.png" });
  await dlg.getByRole("button", { name: "Close" }).last().click();
  await logout(page);

  // Auditor: sees the donations and receipts, prints nothing
  await login(page, "auditor1");
  await page.goto(`/register?account=${accts[0].id}&txn=${t.id}`);
  await page.getByRole("button", { name: "Donation receipt…" }).click();
  const ad = page.getByRole("dialog", { name: `Donation receipt – deposit #${t.id}` });
  await ad.getByText(/^Printed receipts/).click();
  await expect(ad.getByTestId("donation-receipts").getByRole("row")).toHaveCount(4);
  await expect(ad.getByRole("button", { name: /Print|Preview/ })).toHaveCount(0);
  await expect(ad.getByRole("button", { name: "Save", exact: true })).toHaveCount(0);
  await ad.getByRole("button", { name: "Close" }).last().click();
  await logout(page);
});

// ---------------------------------------------------------------- 2.2.0 #325: the shared envelope library
test("#325: envelopes are one library tagged by feature; Donations Setup adds one and sets the receipt's window options", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "Envelopes", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Envelopes", exact: true })).toBeVisible();
  const lib = page.getByTestId("envelope-library");
  const first = lib.getByRole("row", { name: /^#10 envelope Payments/ });
  await expect(first).toContainText("Payments");              // upgraded and Payments-created templates: Payments
  await expect(page.getByTestId("no-default-donations")).toBeVisible();
  await rowAction(lib, "#10 envelope", "Use for Donations");
  await expect(lib.getByRole("row", { name: /^#10 envelope Payments, Donations/ })).toContainText("Payments, Donations");
  await expect(page.getByTestId("no-default-donations")).toHaveCount(0);
  await page.screenshot({ path: "e2e-screenshots/light-envelope-library.png" });
  // Donations Setup lists it as the Donations default; its editor says it is shared with Payments
  await page.getByRole("link", { name: "Donations Setup" }).click();
  const envs = page.getByTestId("envelopes-donations");
  const mine = envs.getByRole("row", { name: /^#10 envelope Default/ });
  await expect(mine).toContainText("Payments");                    // also used for Payments
  await mine.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByTestId("envelope-shared")).toContainText("Also used for Payments");
  await expect(page.getByRole("button", { name: "Duplicate for Donations only" })).toBeVisible();
  await page.getByRole("button", { name: "Back to Donations Setup" }).click();
  // the receipt's window options are there; a window receipt hides the envelope step (left off here)
  await expect(page.getByLabel("Address for a window envelope")).toHaveValue("NONE");
  await page.getByLabel("Fold marks", { exact: true }).selectOption("FRONT");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await logout(page);
});

// ---------------------------------------------------------------- 2.2.0 #325: Donations page
test("#325: a receipt before the money and an item on the Donations page, then Create transaction", async ({ page }) => {
  test.setTimeout(150_000);
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Donations", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Donations", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "New donation" }).click();
  const dlg = page.getByRole("dialog", { name: "New donation" });
  await dlg.getByRole("combobox", { name: "Donor (entity)" }).fill("Sample Donor Alpha");
  await page.getByRole("option", { name: /Sample Donor Alpha/ }).first().click();
  await dlg.getByLabel("Line 1 amount").fill("250.00");
  await dlg.getByLabel("Purpose (optional)").first().fill("New flags");
  await dlg.getByRole("button", { name: "+ Add line" }).click();
  await dlg.getByRole("checkbox", { name: "Item (not money)" }).nth(1).check();
  await expect(dlg.getByText("Estimated value for our records (not printed)")).toBeVisible();
  await dlg.getByLabel("Line 2 description").fill("Television, 55 inch");
  await expect(dlg.getByText(/Value not entered/)).toBeVisible();
  await dlg.getByRole("button", { name: "Save donation" }).click();
  const ed = page.getByRole("dialog", { name: /Donation #\d+ – Sample Donor Alpha/ });
  await expect(ed.getByText("Awaiting deposit")).toBeVisible();
  // not received: the receipt prints the date blank, after a confirmation
  await ed.getByRole("button", { name: "Print receipt" }).click();
  const conf = page.getByRole("dialog", { name: "Confirmation required" });
  await expect(conf).toContainText("not received yet");
  await conf.getByLabel("I have reviewed these warnings and explicitly confirm.").check();
  await conf.getByRole("button", { name: "Confirm and continue" }).click();
  const pv = page.getByRole("dialog", { name: "Donation receipt" });
  await expect(pv.getByRole("button", { name: "Print…" })).toBeVisible();
  await pv.getByRole("button", { name: "Close" }).first().click();
  await expect(ed.getByRole("region", { name: "Receipts" })).toContainText("date received left blank");
  // the donor's envelope, from the envelope tagged for Donations (its default first); the test is not kept
  const envPanel = ed.getByTestId("receipt-envelope");
  await expect(envPanel.getByLabel("Envelope", { exact: true })).toContainText("#10 envelope (default)");
  await envPanel.getByRole("button", { name: "Test on plain paper" }).click();
  const et = page.getByRole("dialog", { name: "Envelope test (plain paper)" });
  await expect(et.getByRole("button", { name: "Print…" })).toBeVisible();
  await et.getByRole("button", { name: "Close" }).first().click();
  await page.screenshot({ path: "e2e-screenshots/light-donation-page.png" });
  await ed.getByRole("button", { name: "Close" }).first().click();
  await expect(page.getByRole("radio", { name: /Awaiting deposit \(\d+\)/ })).toBeVisible();
  // the money arrives: Create transaction
  await page.getByRole("button", { name: "Create transaction" }).click();
  const ct = page.getByRole("dialog", { name: "Create transaction from donations" });
  await ct.getByRole("checkbox", { name: /Sample Donor Alpha \$250\.00/ }).check();
  await ct.getByRole("button", { name: "Continue" }).click();
  const tf = page.getByRole("dialog", { name: /New deposit from donations/ });
  await expect(tf.getByText(/Donation #\d+ – Sample Donor Alpha/)).toBeVisible();
  await expect(tf.getByLabel("Allocation 1 Amount")).toHaveValue("250.00");
  const budget = tf.getByLabel("Allocation 1 Budget");
  await budget.selectOption({ index: 1 });
  await tf.getByRole("button", { name: "Save" }).click();
  const c2 = page.getByRole("dialog", { name: "Confirmation required" });
  // the save may ask for a confirmation first (e.g. a cross-Fiscal-Year date): wait for that dialog or the form closing
  await expect.poll(async () => (await c2.isVisible()) || (await tf.count()) === 0).toBe(true);
  if (await c2.isVisible()) {
    await c2.getByLabel("I have reviewed these warnings and explicitly confirm.").check();
    await c2.getByRole("button", { name: "Confirm and continue" }).click();
  }
  await expect(tf).toHaveCount(0);
  await expect(page.getByRole("row", { name: /Sample Donor Alpha/ }).first()).toContainText("Not received");   // the TV isn't here yet
  await logout(page);
});

// ---------------------------------------------------------------- 2.2.0 #256: year-end statements, donor report
test("#256: a Register User prints a year-end giving statement; the donor report totals by year", async ({ page }) => {
  test.setTimeout(120_000);
  const year = String(new Date().getFullYear());
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Donations", exact: true }).click();
  await page.getByRole("tab", { name: "Year-end statements" }).click();
  await page.getByLabel("Year", { exact: true }).selectOption(year);
  const list = page.getByRole("table", { name: `Year-end statements ${year}` });
  const alpha = list.getByRole("row", { name: /Sample Donor Alpha/ });
  await expect(alpha).toContainText("Not printed");
  await alpha.getByRole("button", { name: /Open statement/ }).click();
  const dlg = page.getByRole("dialog", { name: `Year-end statement ${year} – Sample Donor Alpha` });
  await expect(dlg.getByRole("table", { name: "Donations in the year" })).toContainText("$250.00");
  await dlg.getByRole("button", { name: "Print statement" }).click();
  const conf = page.getByRole("dialog", { name: "Confirmation required" });
  const pv = page.getByRole("dialog", { name: "Year-end statement", exact: true });
  await expect.poll(async () => (await conf.isVisible()) || (await pv.isVisible())).toBe(true);
  if (await conf.isVisible()) {
    await conf.getByLabel("I have reviewed these warnings and explicitly confirm.").check();
    await conf.getByRole("button", { name: "Confirm and continue" }).click();
  }
  await expect(pv.getByRole("button", { name: "Print…" })).toBeVisible();
  await pv.getByRole("button", { name: "Close" }).first().click();
  await expect(dlg.getByTestId("statement-history")).toContainText(`S-${year}-0001`);
  await expect(dlg.getByRole("button", { name: "Print duplicate" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/light-year-end-statement.png" });
  await dlg.getByRole("button", { name: "Close" }).first().click();
  // the donor report: a column per year and the total
  await page.getByRole("tab", { name: "Donor report" }).click();
  const rep = page.getByRole("table", { name: "Donor report" });
  await expect(rep.getByRole("row", { name: /Sample Donor Alpha/ })).toBeVisible();
  await expect(rep.getByRole("columnheader", { name: year })).toBeVisible();
  await logout(page);
});

test("#125: an Administrator reinitializes (keeping the users); everyone sees the notice until it is acknowledged", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "Advanced");
  await expect(page.getByRole("heading", { name: "Advanced", exact: true })).toHaveCount(0);   // build 13: not "Advanced" twice
  await page.getByTestId("reinitialize").locator("summary", { hasText: "Reinitialize" }).click();
  await page.getByLabel('Type "reinitialize" to confirm').fill("reinitialize");
  await page.getByLabel("Your password").last().fill(PW);
  await page.getByRole("button", { name: "Reinitialize" }).click();
  await expect(page.getByTestId("reinit-done")).toContainText("--use-server-key", { timeout: 30_000 });
  await page.goto("/");
  await expect(page.getByTestId("reinitialized-banner")).toContainText("reinitialized by Pat Example - admin");
  await logout(page);
  await login(page, "bm1");
  await expect(page.getByTestId("reinitialized-banner")).toBeVisible();
  await expect(page.getByTestId("reinitialized-banner").getByRole("button")).toHaveCount(0);
  await logout(page);
  await login(page, "admin");
  await page.getByTestId("reinitialized-banner").getByRole("button", { name: "Acknowledge for everyone" }).click();
  await expect(page.getByTestId("reinitialized-banner")).toHaveCount(0);
});
// ---------------------------------------------------------------- 2.2.0 #280: organization branding
const BRAND_LOGO = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAKAAAAAwCAIAAAAZy+Y5AAAAlUlEQVR42u3cMQ5AQBBA0VlxC0qOtw7jeloH0ck2thEi671WIfEzilmRhjwF7eo8AoERGIERGIERmFJ/dWFft6fvPS6zACYYgRFYYARGYARGYAQmbm6yvuCFbVobKjtBE+wVjcAIjMAIjMAILDACIzACE38+bPBdrQlGYIERGIERGIERGIE5JT9CM8EIjMAIjMAITOkAyvUIbD4P5UMAAAAASUVORK5CYII=", "base64");
test("#280: an Administrator brands reports - a palette, a custom palette checked for contrast, a logo", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "Branding");
  await expect(page).toHaveURL(/\/about\/branding$/);
  const card = page.getByRole("region", { name: "Organization branding" });
  await expect(card.getByRole("radio", { name: /PennyWarden/ })).toBeChecked();
  await card.getByRole("radio", { name: /Forest/ }).check();
  await card.getByLabel("Footer text (optional)").fill("Serving the community since 1952");
  await card.getByRole("button", { name: "Save branding" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  // custom: generated from two colors, then a text color too light is caught before saving
  await card.getByRole("radio", { name: "Custom" }).check();
  await card.getByLabel("Primary color", { exact: true }).fill("#00658f");
  await card.getByLabel("Secondary color", { exact: true }).fill("#e0a100");
  await card.getByRole("button", { name: "Generate recommended palette" }).click();
  await card.getByText("Color roles", { exact: true }).click();
  await card.getByLabel("Text on Primary", { exact: true }).fill("#5d8fb0");
  await expect(card.getByTestId("branding-contrast")).toContainText("WCAG AA");
  await expect(card.getByRole("button", { name: "Save branding" })).toBeDisabled();
  await card.getByLabel("Text on Primary", { exact: true }).fill("#ffffff");
  await expect(card.getByRole("button", { name: "Save branding" })).toBeEnabled();
  await card.getByRole("button", { name: "Save branding" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  // the logo shows in the live preview at once
  await card.getByLabel("Full logo image").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: BRAND_LOGO });
  await expect(page.getByTestId("branding-preview").getByRole("img", { name: "Full logo" })).toBeVisible();
  await card.screenshot({ path: "e2e-screenshots/light-branding.png" });
  await card.getByRole("button", { name: "Reset to the PennyWarden palette" }).click();
  await expect(card.getByRole("radio", { name: /PennyWarden/ })).toBeChecked();
});

// ---------------------------------------------------------------- 2.3.0 #386: dual branding
test("#386: light and dark themes - presentations dark for a new setup, a dark palette edited directly, logos for dark backgrounds", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "System/About" }).click();
  await aboutTab(page, "Branding");
  const card = page.getByRole("region", { name: "Organization branding" });
  // a new installation: printed reports light, presentations dark
  await expect(card.getByLabel("Theme for PDF reports (printed)")).toHaveValue("LIGHT");
  await expect(card.getByLabel("Theme for Presentations (.pptx)")).toHaveValue("DARK");
  await card.getByRole("tab", { name: "Dark theme" }).click();
  await expect(page.getByTestId("branding-preview-dark")).toBeVisible();
  await card.getByRole("radio", { name: /Ocean/ }).check();
  // any color can be changed directly: the palette becomes Custom
  await card.getByText("Color roles", { exact: true }).click();
  await card.getByLabel("Text on Primary", { exact: true }).fill("#001e2f");
  await expect(card.getByRole("radio", { name: "Custom" })).toBeChecked();
  // the guardrail holds on the dark theme too
  await card.getByLabel("Text", { exact: true }).fill("#303030");
  await expect(card.getByTestId("branding-contrast")).toContainText("WCAG AA");
  await expect(card.getByRole("button", { name: "Save branding" })).toBeDisabled();
  await card.getByLabel("Text", { exact: true }).fill("#e0e3e8");
  await card.getByLabel("Use a separate logo on dark backgrounds").check();
  await card.getByRole("button", { name: "Save branding" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  await card.getByLabel("Full logo for dark backgrounds image").setInputFiles({ name: "logo-dark.png", mimeType: "image/png", buffer: BRAND_LOGO });
  await expect(page.getByTestId("branding-preview-dark").getByRole("img", { name: "Full logo" })).toBeVisible();
  await card.screenshot({ path: "e2e-screenshots/light-branding-dark-theme.png" });
  // the light theme is unchanged
  await card.getByRole("tab", { name: "Light theme" }).click();
  await expect(page.getByTestId("branding-preview")).toBeVisible();
});

// ---------------------------------------------------------------- 2.2.0 #315 / #316: entity names
test("#315 / #316: first and last name, a display name and mailing address; each user's name order", async ({ page }) => {
  await login(page, "ru1", "Brand-New-Pass-99");
  await page.getByRole("link", { name: "Entities" }).click();
  await page.getByRole("button", { name: "New entity" }).click();
  const dlg = page.getByRole("dialog", { name: "New entity" });
  await dlg.getByLabel("Type").selectOption("INDIVIDUAL");
  await dlg.getByLabel("First name (required)").fill("Robin");
  await dlg.getByLabel("Last name").fill("Zephyr");
  await dlg.getByLabel("Display name same as Name").uncheck();
  await dlg.getByLabel("Display name", { exact: true }).fill("Robin Z. (volunteer)");
  await dlg.getByLabel("Mailing address same as Address").uncheck();
  await dlg.getByLabel("Mailing address line 1").fill("P.O. Box 15");
  await page.screenshot({ path: "e2e-screenshots/light-entity-names.png" });
  await dlg.getByRole("button", { name: "Save" }).click();
  const conf = page.getByRole("dialog", { name: "Confirmation required" });
  await expect.poll(async () => (await conf.isVisible()) || (await dlg.count()) === 0).toBe(true);
  if (await conf.isVisible()) {
    await conf.getByLabel("I have reviewed these warnings and explicitly confirm.").check();
    await conf.getByRole("button", { name: "Confirm and continue" }).click();
  }
  await expect(dlg).toHaveCount(0);
  // the list shows the display name with the name beside it
  await expect(page.getByRole("row", { name: /Robin Z\. \(volunteer\)/ })).toContainText("Robin Zephyr");
  // a second person, with no display name of their own (the earlier entities were reinitialized away by #125)
  const post = await apiAs(page);
  expect((await post("/api/entities", { entity_type: "INDIVIDUAL", first_name: "Jordan", last_name: "Quill",
                                           confirmations: ["DUPLICATE_ENTITY"] })).status()).toBe(201);
  // My account: Last, First - Individuals without a display name of their own show and sort by last name
  await page.goto("/account");
  // the choice is saved to the account: wait for that before leaving the page
  await Promise.all([page.waitForResponse((r) => r.url().includes("/api/me/preferences") && r.ok()),
                     page.getByLabel("Show people's names as").selectOption("LAST_FIRST")]);
  await page.goto("/entities");
  await expect(page.getByRole("cell", { name: /^Quill, Jordan/ })).toBeVisible();
  await page.goto("/account");
  await Promise.all([page.waitForResponse((r) => r.url().includes("/api/me/preferences") && r.ok()),
                     page.getByLabel("Show people's names as").selectOption("FIRST_LAST")]);
  await logout(page);
});
