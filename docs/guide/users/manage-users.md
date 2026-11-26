![Users](../img/users.png)

Administrators (and, read-only, Auditors) manage accounts here.
1. **New user**: username, first and last name, display name, email, security domain and roles, and an **Initial
   password**. On a server, pick one security domain and then its roles: an Administrator can't also be a Financial
   user or an Auditor, and a Financial user can't also be an Auditor. A local install allows roles of every domain on
   one account. See [Roles and responsibilities](roles-and-responsibilities.md) for what each role can do.
2. The user signs in, chooses a new password and security questions (and on a server sets up two-step verification).

- Search and filter by **Roles**, **Security domain** and **Status**; click a heading to sort.
- **⋯** actions: reset password, **Reset two-step verification** (tick **Possible compromise** if the key may be
  exposed), **Reset security questions**, enable a disabled account, deactivate.
- On a server, an Administrator can't change their own roles or deactivate themselves — keep at least two
  Administrators.
- Every sign-in, password change, role change and reset is recorded in the Audit Log.
