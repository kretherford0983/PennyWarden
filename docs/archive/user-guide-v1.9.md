# What's new in 1.9 — quick guide

*1.9.0: one person can run a local install with a single account; scheduled automatic backups.*

## 1.9.0: one account on a local install
On a **local install** (PennyWarden on your own Windows, Mac or Linux computer) the person who sets it up gets every
role: Administrator, Budget Manager, Budget Admin, Register User, Register Admin and Auditor. One account can manage
users, keep the budgets and the register, and read the audit log — no second account just to switch hats.

- **Users → New user / Edit:** on a local install all roles are listed together under *Administration*,
  *Financial* and *Audit*; tick any combination. *Budget Admin* still needs *Budget Manager*, and *Register Admin*
  needs *Register User*.
- **Already using PennyWarden locally?** Your account keeps its roles. Open **Users**, edit your own account and
  tick the roles you want. At least one active Administrator must remain.
- **On a server** nothing changes: each user has roles of one security domain, and Administrators cannot change
  their own roles.

## 1.9.0: automatic backups
**System/About → Backup / Restore → Scheduled** (Administrators):

1. Tick **Back up automatically**, choose **Daily** or **Weekly**, the day and the time (this computer's time).
2. Enter the **folder** — for example an external drive or a network share that this computer shows as a drive or
   folder — and press **Test**. On a server you pick from the folders the server owner set up.
3. Choose how many backups to **keep**, e.g. 3 daily, 2 weekly, 2 monthly. Older ones are removed automatically;
   other files in the folder are never touched.
4. Set the **backup passphrase** and confirm with your password, then **Save**. **Write the passphrase down
   somewhere safe**: restoring a scheduled backup needs it, and nobody can recover it.

**Run now** makes a backup at once. The list below shows the recent backups. If a backup fails (the drive is
unplugged, the network share is down), PennyWarden tries again after 1 hour, then 2, 4 … and shows a red banner to
Administrators until a backup works again. A backup missed because PennyWarden was not running is made shortly after
it starts.

To restore one, use the **Restore** tab as for a downloaded backup, with the backup passphrase.
