/** v1.3 CR-014: small inline navigation icons (original line drawings; no icon library dependency). */
import type { ReactNode } from "react";

const paths: Record<string, ReactNode> = {
  "/": <><path d="M3 11l9-7 9 7" /><path d="M5 10v10h5v-6h4v6h5V10" /></>,
  "/fiscal-years": <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /><path d="M7 14h3M14 14h3M7 17h3" /></>,
  "/budgets": <><path d="M12 3v9l7.8 4.5" /><circle cx="12" cy="12" r="9" /></>,
  "/bank-accounts": <><path d="M3 10l9-6 9 6" /><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8" /><path d="M3 20h18" /></>,
  "/register": <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>,
  "/entities": <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5" /><circle cx="17.5" cy="9" r="2.5" /><path d="M17 14.5c2.4.2 4 1.8 4.5 4.5" /></>,
  "/payments": <><path d="M4 7h16v10H4z" /><path d="M8 11h5M8 14h3" /><path d="M16 10v4M14.5 11.2c0-.7.7-1.2 1.5-1.2s1.5.4 1.5 1.1-.7 1-1.5 1.1-1.5.4-1.5 1.1.7 1.1 1.5 1.1 1.5-.5 1.5-1.2" /></>, // 2.0.0 (#164)
  "/check-setup": <><rect x="3" y="6" width="18" height="12" rx="1.5" /><path d="M6 10h7M6 14h4M15 14.5c1-1.6 2-1.6 3 0" /></>, // 2.0.0 (#156)
  "/fundraisers": <><path d="M12 20s-7-4.4-7-9.6C5 7.5 7 5.5 9.4 5.5c1.2 0 2 .5 2.6 1.4.6-.9 1.4-1.4 2.6-1.4C17 5.5 19 7.5 19 10.4 19 15.6 12 20 12 20z" /><path d="M12 9.5v5M10 12h4" /></>,
  "/reports": <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /><path d="M9 17v-3M12 17v-6M15 17v-4" /></>,
  "/users": <><circle cx="12" cy="8" r="4" /><path d="M4 21c1-4.2 4.2-6.5 8-6.5s7 2.3 8 6.5" /></>,
  "/audit-log": <><path d="M12 3l8 3v6c0 4.6-3.3 7.9-8 9-4.7-1.1-8-4.4-8-9V6z" /><path d="M9 12l2 2 4-4" /></>,
  "/about": <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></>,
};

export function NavIcon({ to }: { to: string }) {
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {paths[to] || <circle cx="12" cy="12" r="8" />}
    </svg>
  );
}
