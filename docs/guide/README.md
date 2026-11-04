# PennyWarden user guide

Applies to PennyWarden 2.4. In the app, **Help** opens this guide; it is also on [pennywarden.org](https://pennywarden.org/guide/), where earlier versions can be chosen. The pages are written in `<chapter>/<page>.md`; the order, titles and summaries are in `guide.json`; pictures are made by `scripts/docs_screenshots.mjs`.

## Getting started

What PennyWarden is for, who does what, signing in and finding your way around.

- [Welcome to PennyWarden](getting-started/welcome.md) — What PennyWarden does and how this guide is organized.
- [Who does what](getting-started/who-does-what.md) — The roles and why duties are separated.
- [The first start](getting-started/first-start.md) — Setting up a new installation with the Initialization Wizard.
- [Signing in](getting-started/sign-in.md) — Signing in, two-step verification and the password rules.
- [Forgot your password?](getting-started/forgot-password.md) — Resetting a forgotten password with your security questions.
- [Finding your way](getting-started/finding-your-way.md) — The menu, the top bar and how PennyWarden shows things.

## My account

Your password, two-step verification, security questions and display choices.

- [Your account page](my-account/my-account.md) — What you can change on My account.
- [Changing your password](my-account/change-password.md) — Choosing a new password.
- [Two-step verification](my-account/two-step-verification.md) — Setting up an authenticator app and using recovery codes.

## Dashboard

The page that opens after you sign in.

- [What the Dashboard shows](dashboard/dashboard.md) — Balances, budgets, attention items and charts.
- [Customizing the Dashboard](dashboard/customize-dashboard.md) — Choosing which sections and charts you see.

## Fiscal Years

Creating, approving and closing the years your budgets cover.

- [About Fiscal Years](fiscal-years/about-fiscal-years.md) — Draft, Approved and Closed, and how quarters work.
- [Creating a Fiscal Year](fiscal-years/create-fiscal-year.md) — Budget Managers: a new year, optionally with last year's budgets.
- [The Fiscal Year page](fiscal-years/fiscal-year-page.md) — Budgets by quarter, documents, the documentation review and closure readiness.
- [Approving a Fiscal Year](fiscal-years/approve-fiscal-year.md) — Budget Managers: locking the year's budgets.
- [Closing a Fiscal Year](fiscal-years/close-fiscal-year.md) — Budget Managers: what must be done first and what closing does.
- [Planning the next year](fiscal-years/planning-sheet.md) — The planning sheet for the budget meeting.

## Budgets

Income and expense budgets, sub-budgets, history across years and Invoiced Income.

- [About budgets](budgets/about-budgets.md) — Codes, sub-budgets, Other, gross amounts and status marks.
- [Managing budgets](budgets/manage-budgets.md) — Budget Managers: new budgets, unlocking, rejecting, inactivating and deleting.
- [History across years](budgets/budget-history.md) — Linking budgets across years and entering years before PennyWarden.
- [Invoiced Income budgets](budgets/invoiced-income-budgets.md) — Budget Managers: the budgets invoice money goes to.

## Bank Accounts

Accounts, balances and closing an account.

- [Setting up a bank account](bank-accounts/set-up-account.md) — Budget Managers: a new account and its register.
- [Balances](bank-accounts/balances.md) — Current and Available balances, and accounts without a register.
- [Closing an account](bank-accounts/close-account.md) — When an account can be closed.

## Entities

The people and organizations you pay or receive money from.

- [About entities](entities/entities.md) — What an entity is and who looks after them.
- [Adding or editing an entity](entities/add-entity.md) — Names, addresses, phone numbers and duplicates.
- [Financial Institutions and your organization](entities/special-entities.md) — Entities with special rules.

## Register

Recording deposits and withdrawals for each bank account.

- [Reading the register](register/read-register.md) — Balances, filters, sorting and a transaction's details.
- [Entering a transaction](register/enter-transaction.md) — Register Users: a deposit or a withdrawal.
- [Split transactions](register/split-transaction.md) — One bank entry over several budgets.
- [Transfers between accounts](register/transfer.md) — Moving money between two of your accounts.
- [Changing a transaction](register/change-transaction.md) — What can be edited and how.
- [Voiding or deleting a transaction](register/void-or-delete.md) — Taking a transaction back.
- [Reviews and missing checks](register/reviews-and-missing-checks.md) — Cross-year allocations and gaps in the check sequence.
- [Printing the register](register/print-register.md) — A clean portrait printout of what you see.

## Attachments

Receipts, invoices and other documents on records.

- [Attaching documents](attachments/attachments.md) — File types, the viewer and 'No attachment will be provided'.

## Reports

The report catalog and what each report is for.

- [Running a report](reports/reports-catalog.md) — Finding, running and re-running reports.
- [The reports](reports/report-list.md) — What each report is for.

## Events & Fundraisers

Gathering everything spent and received for an event.

- [About Events & Fundraisers](events/about-events.md) — What the module does and the two types.
- [Setting up an event](events/set-up-event.md) — Budget Managers: a new fundraiser or event.
- [Managing an event](events/manage-event.md) — Buckets, cash floats, exclusions and documents.
- [Event reports](events/event-reports.md) — The stakeholder report, the presentation and the yearly report.

## Payments and check printing

Paying bills and printing checks on pre-printed check stock.

- [About payments](payments/payments-overview.md) — What the Payments module does and who does what.
- [Printing a check](payments/print-a-check.md) — Register Users: entering a bill and printing its check.
- [Payments Setup](payments/payments-setup.md) — Administrators: check styles, test prints and calibration.
- [Cover letters](payments/cover-letters.md) — Administrators: the payment letter printed with a check.

## Donations

Donation receipts, year-end statements and the donor report.

- [Donations Setup](donations/donations-setup.md) — Administrators: receipt and statement letters.
- [Donation receipts](donations/donation-receipts.md) — Register Users: marking donations and printing receipts.
- [Year-end statements and the donor report](donations/year-end-statements.md) — Each donor's giving for the year.

## Invoices

Billing members and customers from a product catalog, with sales tax and payments.

- [About invoices](invoices/about-invoices.md) — What the module does, who does what, and the order to set it up.
- [Invoices Setup](invoices/invoices-setup.md) — Administrators: numbering, terms, fields and the invoice PDF.
- [The invoice PDF](invoices/invoice-pdf.md) — Administrators: letterhead, logo, columns, fold marks and window envelopes.
- [The product catalog](invoices/catalog.md) — Invoice Managers: what the catalog holds.
- [Categories](invoices/categories.md) — Invoice Managers: a category's budget and product code pattern.
- [Setting up sales tax](invoices/set-up-tax.md) — Invoice Managers: tax rates, tax groups and assigning them to products.
- [Adding a product](invoices/add-product.md) — Invoice Managers: choose the category first, then the rest.
- [Custom fields](invoices/custom-fields.md) — Extra details on invoices, on every line, or on lines of chosen products.
- [Tax-exempt customers](invoices/tax-exempt-customers.md) — Customers who are charged no sales tax.
- [Creating an invoice](invoices/create-invoice.md) — Invoice Managers: a draft from catalog products.
- [Sending, revising and voiding](invoices/send-revise-void.md) — Invoice Managers: from draft to sent, and correcting it.
- [Recording a payment](invoices/record-payment.md) — Register Users: the deposit from an invoice.
- [Many customers at once](invoices/batches.md) — Invoice Managers: a batch of invoices for dues and the like.
- [Emailing invoices](invoices/email-invoices.md) — Sending invoices and statements by email.
- [Invoice reports](invoices/invoice-reports.md) — Open invoices, aging, statements, sales tax, and sales reports for the board.

## Reminders and notifications

Reminders for you or the whole organization.

- [Reminders](notifications/reminders.md) — Creating, resolving and repeating reminders.

## Envelopes and signers

Shared by Payments, Donations and Invoices.

- [Envelopes](envelopes-and-signers/envelopes.md) — Administrators: #10 envelope templates.
- [Signers](envelopes-and-signers/signers.md) — Administrators: who signs checks and letters.

## Users

User accounts and roles.

- [Managing users](users/manage-users.md) — Administrators: new users, roles and resets.

## Audit Log

Every change, who made it and when.

- [The Audit Log](audit-log/audit-log.md) — Reading, filtering and exporting the log.

## System/About

Looking after the installation.

- [The System/About tabs](system-about/system-about-tabs.md) — What each tab is for.
- [Optional modules](system-about/optional-modules.md) — Administrators: turning modules on and off.
- [Organization logos](system-about/organization-logos.md) — One logo for letters, envelopes, invoices, donation letters and Branding.
- [Branding](system-about/branding.md) — Administrators: colors and logos for reports and presentations.

## Backup and restore

Keeping copies of your data and bringing them back.

- [Making backups](backup-and-restore/backups.md) — Administrators: manual and scheduled backups.
- [Restoring a backup](backup-and-restore/restore.md) — Administrators: bringing a backup back.

## Installing and the demo

Downloads, server installs, upgrading and the demo.

- [Installing and upgrading](installing/installing.md) — Where to find the installers and the server guides.
- [The demo](installing/demo.md) — Trying PennyWarden with a made-up organization.

## Reference

The full technical guides for check printing and backups.

- [Check printing](../check-printing.md) — The complete check printing guide.
- [Backup and restore (full guide)](../backup-restore.md) — The complete backup and restore guide.
