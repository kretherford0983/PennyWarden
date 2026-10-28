import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";

/**
 * 2.2.0 (#343): the password requirements beside a new-password field, ticked off as they are met.
 *
 * The requirements and their numbers come from the server (`GET /api/auth/password-policy`), so this file keeps no
 * copy of the rules: it only knows how to tick each requirement `id`. An `id` it does not know, or one marked
 * `server_only`, stays unticked and is checked when the password is saved. The server stays the authority.
 */
export type PasswordRequirement = { id: string; text: string; applies: string; server_only?: boolean };
export type PasswordPolicy = { min_length: number; max_length: number; requirements: PasswordRequirement[] };

let cached: Promise<PasswordPolicy> | null = null;

export function usePasswordPolicy(): PasswordPolicy | null {
  const [p, setP] = useState<PasswordPolicy | null>(null);
  useEffect(() => {
    let live = true;
    if (!cached) {
      cached = api.get("/api/auth/password-policy");
      cached.catch(() => { cached = null; });
    }
    cached.then((v) => { if (live) setP(v); }, () => undefined);
    return () => { live = false; };
  }, []);
  return p;
}

/** Where the list is shown: which comparisons make sense there. */
export type ChecklistContext = {
  username?: string;
  current?: string;          // a current password is typed (Change password)
  confirm?: string;          // a confirmation field exists
  temporary?: boolean;       // after a temporary password (only the server can compare)
};

function applies(r: PasswordRequirement, c: ChecklistContext): boolean {
  if (r.applies === "always") return true;
  if (r.applies === "change") return c.current !== undefined;
  if (r.applies === "confirm") return c.confirm !== undefined;
  if (r.applies === "temporary") return !!c.temporary;
  return false;
}

const LETTER = /\p{L}/u;
const DIGIT = /\p{Nd}/u;

/** null = can't be checked here (checked when the password is saved). */
function met(r: PasswordRequirement, p: PasswordPolicy, pw: string, c: ChecklistContext): boolean | null {
  if (r.server_only) return null;
  switch (r.id) {
    case "length": return pw.length >= p.min_length && pw.length <= p.max_length;
    case "letter_digit": return LETTER.test(pw) && DIGIT.test(pw);
    case "not_username": {
      const u = (c.username || "").trim().toLowerCase();
      return pw.length > 0 && (!u || pw.trim().toLowerCase() !== u);
    }
    case "differs_current": return pw.length > 0 && pw !== (c.current || "");
    case "confirm_matches": return pw.length > 0 && pw === (c.confirm || "");
    default: return null;
  }
}

export function PasswordChecklist({ password, context, id }: { password: string; context: ChecklistContext; id?: string }) {
  const policy = usePasswordPolicy();
  if (!policy) return null;
  const items = policy.requirements.filter((r) => applies(r, context));
  return (
    <div className="pw-checklist" id={id}>
      <p className="field-label">Password requirements</p>
      {/* (no aria-label on the list: "Password …" labels would make getByLabel("Password") ambiguous for assistive
          tech and tests alike; the new-password input points here with aria-describedby instead) */}
      <ul aria-live="polite" data-testid="password-checklist">
        {items.map((r) => {
          const m = met(r, policy, password, context);
          const cls = m === null ? "pending" : m ? "met" : "unmet";
          return (
            <li key={r.id} className={cls} data-req={r.id} data-state={cls}>
              <span className="pw-mark" aria-hidden="true">{m ? "✓" : m === null ? "…" : "○"}</span>
              <span>{r.text}</span>
              <span className="sr-only">{m === null ? " (checked when you save)" : m ? " (met)" : " (not met)"}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** The fields on the left half, the checklist on the right half; stacked on a narrow screen. */
export function PasswordFieldsWithChecklist({ children, checklist }: { children: ReactNode; checklist: ReactNode }) {
  return (
    <div className="pw-split">
      <div className="pw-fields">{children}</div>
      {checklist}
    </div>
  );
}
