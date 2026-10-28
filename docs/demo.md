# The PennyWarden demo (since 2.2.0)

The demo is PennyWarden with a made-up organization already in it — *Riverside Band Boosters* — so you can see what
the application does without entering anything first. Everything in it is invented: the organization, people,
vendors, account numbers and documents.

## Install it

1. Install PennyWarden on your own computer (Windows or Mac; see the [README](../README.md) or pennywarden.org).
2. Download `pennywarden-demo-<version>.fmbak` from the [latest release](https://github.com/kretherford0983/PennyWarden/releases/latest)
   (pennywarden.org → *Try the demo* links to it and shows its SHA-256).
3. Start PennyWarden. On the first screen choose **Restore from a backup instead**, pick the file and enter the
   passphrase **`pennywarden demo`**.
4. Sign in with the password **`Demo-PennyWarden-2026`** as one of:

| Sign-in | Role | Try |
|---|---|---|
| `demo-admin` | Administrator | users and roles, backups, System/About — no financial records (separation of duties) |
| `demo-budget` | Budget Manager | Fiscal Years, budgets, bank accounts, fundraisers, reports, the Budget Review |
| `demo-register` | Register User | the register, attachments, payments and printed checks |
| `demo-auditor` | Auditor | everything read-only, including the audit log |

The current Fiscal Year is the year the demo was built (January to December) with an approved budget; the year before
is closed. A new demo is built with every release.

## What happens to your changes

Nothing you do is kept. PennyWarden puts the demo back as it was:
- **every time it starts**, and
- whenever you choose **Reset demo data** on the banner (also on the sign-in page — if you changed a password or set up
  two-step verification and can't get in, reset).

So try anything: enter and approve, print checks, close a year, add users, change roles — and see it all in the audit
log.

## The demo runs only on your computer

Its passwords and its encryption key are published, so the demo refuses to run in server mode or on a network
address (`--mode server`, `--host 0.0.0.0`): it starts only in local mode on 127.0.0.1. A server refuses to restore it.

## Remove the demo and start fresh

When you are ready to use PennyWarden for your own organization:
- sign in as **`demo-admin`** and choose **Remove the demo and start fresh** on the banner (type REMOVE), or
- quit PennyWarden and run `pennywarden remove-demo` (Windows: `PennyWarden.exe remove-demo`; Mac:
  `/Applications/PennyWarden.app/Contents/MacOS/PennyWarden remove-demo`).

This removes the demo's database, attachments, users, audit log, its published encryption key and the kept demo copy.
Your settings file (`config.toml`) stays. The next screen is the Initialization Wizard, exactly as on a new install,
which creates a new encryption key. Nothing of the demo remains.

Restoring one of your own backups over the demo also replaces it completely and leaves demo mode.

## For maintainers

`python scripts/build_demo.py --out pennywarden-demo-<version>.fmbak` builds the file: it starts a fresh
PennyWarden from the checkout, fills it through the normal web API (`scripts/demo_data.py`), sets the demo marker
(`workspace.demo_mode`) directly in the database file — no web or API path writes it — and makes an encrypted backup
with the published passphrase, plus `<file>.sha256`. The build workflow runs it for every package and attaches the
file to the release; `scripts/release_data.py` lists it for the *Try the demo* section of pennywarden.org.
