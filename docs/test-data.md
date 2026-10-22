# Test data: refreshing a test server (2.1.0, #272)

A **private, synthetic test data set** for trying a test build against a realistic organization without entering
it by hand. A GitHub Actions workflow builds it as a normal encrypted PennyWarden backup, and you restore that backup
on the test server.

The test data set is **never published**:
- it isn't on pennywarden.org and isn't attached to a release;
- the file exists only as a workflow artifact, kept for 7 days, and is encrypted with your backup passphrase;
- the sign-in password and the passphrase come from repository secrets only, and are masked in the log.

The public demo (`scripts/demo_data.py` without `--profile`) is unrelated and unchanged.

## What's in it

**Cedar Valley Community Association**, an invented organization with invented people, vendors and account numbers.
Dates follow the day the data is built, so the current Fiscal Year is always "this year". By default the Fiscal Year
runs July–June; the workflow's *Fiscal Year start month* changes that.

| | |
|---|---|
| **Fiscal Years** | two **Closed** (with approval and audit signoff documents and their Close reports), the current one **Approved**, and the next one a **Draft** whose budgets continue the current ones. Each year after the first continues the year before, so Budget Review has history. |
| **Budgets** | income and expense budgets with sub-budgets (Fundraising, Facility, Fundraising costs), growing a little each year |
| **Register** | about 120 transactions over the three years: deposits, checks, electronic payments (ACH, online portal, debit card, wire), a transfer to savings, attachments, a VOID check, a deleted transaction (its check number released, #289), and the most recent ones still uncleared |
| **Payments** | a voucher check style with a made-up signer; two checks of the current year printed |
| **Donations** | a made-up EIN (00-0000000) and address; a current-year deposit from two donors marked as donations (one with a gala dinner as goods), and both receipts printed (2.1.0, #312) |
| **Fundraisers** | three series, each recorded in PennyWarden for three years plus **four years before PennyWarden entered by hand**:<br>• **Golf Outing**, with buckets and categories, Charge / Less (a card fee) and a contributor override ("Cash" for the raffle table);<br>• **Pancake Breakfast**, held twice a year (spring and fall) and merged into one series;<br>• **Holiday Raffle**.<br>Also an upcoming fundraiser and a cancelled one. |
| **Other** | entities, organization and personal reminders; the Fundraisers, Payments and Donations modules are on |

| Sign-in | Role |
|---|---|
| `admin` | Administrator |
| `budgetmgr` | Budget Manager |
| `bookkeeper` | Register User |
| `auditor` | Auditor |
| `treasurer` | Budget Manager + Register User (also Register Admin, which deletes a transaction in the data set) |

Every test user's password is the `PW_TESTDATA_PASSWORD` secret, which is also the answer to their three security
questions. On a server, each user **enrolls two-step verification at the first sign-in after a restore**: scan the new
QR code each time you refresh.

## One-time setup

In the repository, open **Settings → Secrets and variables → Actions → New repository secret** and add:
- `PW_TESTDATA_PASSWORD`: the test users' password. It must meet the password policy.
- `PW_TESTDATA_PASSPHRASE`: the backup passphrase you'll type when restoring.

Use values that aren't used anywhere else.

The workflow is run by hand, and GitHub only lists a manually run workflow once its file is on the default branch
(`main`). Until then, build the file locally (below).

## Building the file

1. **Actions → Build test data → Run workflow.**
2. Set **Branch (or tag)** to the one the test server runs: `test` (the default), or `develop` / a feature branch to
   try a change.
3. Choose the **Fiscal Year start month** (default 7, July).
4. When it finishes, the run summary shows:
   - the file name;
   - the PennyWarden version and **schema** the file needs;
   - the Fiscal Years, sign-ins and counts.

   Download the file from the run's **Artifacts**. The download is a `.zip` holding the `.fmbak`.

**Schema:** Restore refuses a backup made by a newer schema than the server's ("made by a newer version"). Build from
the branch the server runs, or from an older one. An older backup is migrated during the restore.

### Locally (any branch, no GitHub)

```bash
# a fresh, empty installation on loopback
cd backend && python -m fmpoc --no-browser --port 8790 --data-dir /tmp/pw-testdata &
cd ..
export PW_TESTDATA_PASSWORD='...' PW_TESTDATA_PASSPHRASE='...'   # your own values; never commit them
python scripts/demo_data.py --profile test --fy-start-month 7 --backup test-data.fmbak http://127.0.0.1:8790
```

The generator refuses an installation that's already initialized, so it can't touch real data.

## Restoring on the test server

**Restoring replaces everything on that server:**
- its sign-ins, including yours;
- its Fiscal Years and transactions;
- the data you entered by hand.

Restore keeps one safety copy (`pre-restore/`) and a re-entry report. If you want to keep what's there now, take a
backup of the test server before the first refresh.

- **In the app:** sign in as an Administrator → **System/About → Backups → Restore**. Upload the `.fmbak`, type the
  passphrase and confirm.
- **On the host:**
  ```bash
  sudo pennywarden restore pennywarden-test-data-YYYYMMDD-runN.fmbak --stop-service
  ```
  It asks for the passphrase in a hidden prompt (or use `--passphrase-file`). See [backup-restore.md](backup-restore.md).

Then sign in as any test user with the secret password, and enroll two-step verification when asked.
