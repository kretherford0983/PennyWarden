# What's new in 2.2 — quick guide

*2.2.0 is in progress. The full list is in the [changelog](../CHANGELOG.md).*

## Signing in and passwords

### A wrong password is cleared
When a sign-in is refused (a wrong username or password, or too many attempts), the **Password** field is emptied and
the cursor is put back in it, so you can type the password again straight away. The username stays as you typed it.

### The password requirements, ticked off as you type
Under **My account → Change password** the requirements are listed beside the fields before you start:
- at least 12 characters (at most 128);
- at least one letter and one digit;
- not the same as your username;
- different from your current password;
- *New password* and *Confirm new password* are the same.

Each requirement is **red** until it is met and turns **green with a check mark** once it is. If the change is still
refused (for example, the current password was mistyped), everything you typed stays in the fields.

The same list is shown wherever a new password is chosen: after signing in with a temporary password, under
*Forgot password?*, in the first-run Initialization Wizard, and when an Administrator creates a user or resets a
password. After a temporary password, "different from the temporary password" is checked when you save.

## Two-step verification

### Keep the authenticator you already have
When two-step verification is set up again — for example after an Administrator (or the server command
`reset-mfa`) reset it — you don't have to scan a new QR code. Under the key shown on the setup screen, open **Use my
own key instead** and enter the key from the PennyWarden entry already in your authenticator app, or paste an
`otpauth://totp/…` link exported from the app, then **Use this key** and enter the app's current code as usual.
- The key must be at least 16 characters (letters A–Z and digits 2–7; spaces and lower case don't matter). Keys
  shorter than PennyWarden's own (32 characters) work, with a note.
- Links for codes other than 6 digits every 30 seconds (SHA-1) can't be used.
- Nothing is saved until the code matches, and you get a **new set of recovery codes** as on every setup.
- **Reuse a key only if it was never exposed.** After any security problem use the new key PennyWarden shows.

### Administrators: *Possible compromise*
**Users → ⋯ → Reset two-step** has a **Possible compromise** checkbox. Tick it when the authenticator key may have
been exposed (a stolen phone, a security problem): the user then has to set up with a **newly generated** key, and
*Use my own key instead* explains why it isn't available. On the server command line the same is
`pennywarden reset-mfa --user NAME --compromised` (with `sudo` and `--data-dir` as usual). The audit log records
whether a reset was marked and whether a setup used an own key — never the key itself.
