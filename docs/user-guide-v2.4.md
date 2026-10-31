# What's new in 2.4 — quick guide

*2.4.0 is in progress. The full list is in the [changelog](../CHANGELOG.md).*

## Attachments

### Identical files are stored once
If you attach a file that PennyWarden already has — the same receipt on two transactions, say — it is no longer saved
a second time. Nothing looks different: each record shows its own attachment with the name you gave it, and you can
view, download or remove it exactly as before. Removing it from one record never removes it from another. The saved
copies PennyWarden makes itself (the Close report, check record copies, donation receipts, statements and envelopes)
work the same way.

### Picking the same file twice
When you add a file that is **already attached to the same record**, PennyWarden stops and asks:

- **Cancel** — nothing is added. Use this when you meant to pick a different file (an easy slip when attaching several
  files in a row).
- **Attach anyway** — the file is added a second time.

Attaching the same file to a *different* record does not ask.

### After the upgrade
The first time 2.4 starts, attachments that are identical are linked to one stored file and the extra copies are
removed, freeing disk space. Every file is checked first; anything that doesn't check out is left exactly as it is.
An Administrator can see how many files are shared and how much space was saved in the **Health** section of
**System/About**.
