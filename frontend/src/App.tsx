import { createContext, useContext, useEffect, useState } from "react";
import { api, setCsrf } from "./api";
import { Link, match, useRouter } from "./router";
import { Loading } from "./components";
import { NavIcon } from "./icons";
import InitWizard from "./pages/InitWizard";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Users from "./pages/Users";
import AuditLog from "./pages/AuditLog";
import About from "./pages/About";
import { MfaGate } from "./pages/Mfa";
import FiscalYears from "./pages/FiscalYears";
import FiscalYearDetail from "./pages/FiscalYearDetail";
import Budgets from "./pages/Budgets";
import BankAccounts from "./pages/BankAccounts";
import Register from "./pages/Register";
import Entities from "./pages/Entities";
import Account from "./pages/Account";
import Reports from "./pages/Reports";
import Fundraisers, { FundraiserDetail } from "./pages/Fundraisers";
import CheckSetup from "./pages/CheckSetup";
import Payments from "./pages/Payments";
import Notifications, { REMINDERS_CHANGED } from "./pages/Notifications";
import { AdminSecurityNotices, SignInNotices } from "./pages/Recovery";
import { BackupFailedBanner } from "./pages/ScheduledBackups";
import { UpdateBanner, UpdateIndicator, useUpdates } from "./pages/Updates";

export const ROLE_NAMES: Record<string, string> = {
  ADMINISTRATOR: "Administrator", BUDGET_MANAGER: "Budget Manager", BUDGET_USER: "Budget User",
  REGISTER_USER: "Register User", AUDITOR: "Auditor",
  BUDGET_ADMIN: "Budget Admin", REGISTER_ADMIN: "Register Admin", // 1.7.3 (#52, #53)
};

export interface Me {
  id: number;
  username: string;
  display_name?: string | null; // 1.7.1 (#47): always set; shown in the top bar (#46)
  email: string;
  security_domain: "ADMINISTRATOR" | "FINANCIAL" | "AUDITOR" | "COMBINED"; // 1.9.0 (#54): COMBINED on local installs
  roles: string[];
  permissions: string[];
  theme: "light" | "dark";
  nav_collapsed?: boolean;
  dashboard_charts?: string[];
  dashboard_layout?: { key: string; visible: boolean }[]; // v1.5.0 CR-031
  dashboard_layout_customized?: boolean;
  modules?: { fundraisers?: boolean; checks?: boolean }; // v1.6.0 CR-033; 2.0.0 (#156) Check Printing
  mfa_pending?: "VERIFY" | "ENROLL" | "PASSWORD" | "QUESTIONS" | null; // v1.4.1 CR-018; 1.8.0 (#113) setup steps
  sign_in_notices?: { kind: string; message: string }[]; // 1.8.0 (#113)
  csrf_token: string;
}

const MeCtx = createContext<{ me: Me; can: (p: string) => boolean; refresh: () => Promise<void>; setTheme: (t: "light" | "dark") => void; patchMe: (p: Partial<Me>) => void } | null>(null);

export function useMe() {
  const c = useContext(MeCtx);
  if (!c) throw new Error("no user");
  return c;
}

function applyTheme(t: string) {
  document.documentElement.dataset.theme = t;
}

export default function App() {
  const { path, navigate } = useRouter();
  const [status, setStatus] = useState<any>(null);
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  const loadMe = async () => {
    try {
      const m = await api.get<Me>("/api/auth/me");
      setCsrf(m.csrf_token);
      applyTheme(m.theme);
      setMe(m);
    } catch {
      setCsrf(null);
      applyTheme("light");
      setMe(null);
    }
  };

  const boot = async () => {
    const s = await api.get("/api/system/status");
    // HF-001: load the user first, then switch the status - otherwise the sign-in page flashes (and starts its own
    // CSRF request) between "initialized" and "user loaded".
    if (s.initialized) await loadMe();
    else setMe(null);
    setStatus(s);
  };

  useEffect(() => {
    boot();
    const on = (e: Event) => {
      if ((e as CustomEvent).detail?.code === "MFA_REQUIRED") {
        loadMe(); // still signed in: show the two-step verification screen
        return;
      }
      setCsrf(null);
      setMe(null);
    };
    window.addEventListener("fm:unauthenticated", on);
    return () => window.removeEventListener("fm:unauthenticated", on);
  }, []);

  // v1.5.0: while signing in (login / two-step screens) the address is the dashboard, so a bookmarked page such as
  // /about never survives into the sign-in flow; after signing in the user starts on the dashboard.
  const signingIn = !!status && me !== undefined && (!me || !!me.mfa_pending) && status.initialized;
  useEffect(() => {
    if (signingIn && path !== "/") navigate("/", { replace: true });
  }, [signingIn, path]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!status || me === undefined) return <div className="center"><Loading /></div>;
  if (!status.initialized) return <InitWizard onDone={boot} />;
  if (!me) return <Login workspace={status.workspace_name} onLogin={loadMe} legal={status} />;
  if (me.mfa_pending) return <MfaGate me={me} workspace={status.workspace_name} onDone={loadMe} onLogout={() => { setCsrf(null); setMe(null); }} />;

  const ctx = {
    me,
    can: (p: string) => me.permissions.includes(p),
    refresh: loadMe,
    setTheme: (t: "light" | "dark") => {
      applyTheme(t);
      setMe({ ...me, theme: t });
    },
    patchMe: (p: Partial<Me>) => setMe({ ...me, ...p }),
  };
  return (
    <MeCtx.Provider value={ctx}>
      <Shell workspace={status.workspace_name} warning={status.insecure_transport_warning} mode={status.mode} onLogout={() => { setCsrf(null); setMe(null); }} />
    </MeCtx.Provider>
  );
}

function navFor(me: Me) {
  const fin = [
    ["/", "Dashboard"],
    ["/fiscal-years", "Fiscal Years"],
    ["/budgets", "Budgets"],
    ["/bank-accounts", "Bank Accounts"],
    ["/register", "Register"],
    ["/entities", "Entities"],
    ["/reports", "Reports"],
  ];
  if (me.modules?.fundraisers) fin.splice(6, 0, ["/fundraisers", "Fundraisers"]); // v1.6.0 CR-033 (optional module)
  // 2.0.0 (#164): Payments (Payments module) for Register Users, after Register
  if (me.modules?.checks && me.permissions.includes("checks.print")) fin.splice(fin.findIndex((n) => n[0] === "/register") + 1, 0, ["/payments", "Payments"]);
  // 2.0.0 (#156): Payments Setup (check printing) for Administrators when the Payments module is on
  const checkSetup = me.modules?.checks && me.permissions.includes("checks.setup") ? [["/check-setup", "Payments Setup"]] : [];
  if (me.security_domain === "ADMINISTRATOR") return [["/", "Dashboard"], ["/users", "Users"], ["/audit-log", "Audit Log"], ...checkSetup, ["/about", "System/About"]];
  if (me.security_domain === "AUDITOR") return [...fin, ["/users", "Users"], ["/audit-log", "Audit Log"]];
  if (me.security_domain === "COMBINED") { // 1.9.0 (#54): one person, roles of several domains (local installs)
    const has = (p: string) => me.permissions.includes(p);
    return [...(has("financial.view") ? fin : [["/", "Dashboard"]]), ...(has("users.view") ? [["/users", "Users"]] : []),
      ...(has("audit.view") ? [["/audit-log", "Audit Log"]] : []), ...checkSetup, ...(has("users.manage") ? [["/about", "System/About"]] : [])];
  }
  return fin;
}

function Shell({ workspace, warning, mode, onLogout }: { workspace: string; warning: boolean; mode: string; onLogout: () => void }) {
  const { me, can, setTheme, patchMe } = useMe();
  const updates = useUpdates(); // 1.10.0 (#58)
  // CR-014: collapsible left navigation, remembered per user (like the theme)
  const [collapsed, setCollapsed] = useState(!!me.nav_collapsed);
  const toggleNav = () => {
    const next = !collapsed;
    setCollapsed(next);
    api.put("/api/me/preferences", { nav_collapsed: next }).catch(() => undefined);
  };
  const { path } = useRouter();
  const nav = navFor(me);
  const allowed = new Set(nav.map((n) => n[0]));
  const logout = async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      onLogout();
    }
  };
  const toggleTheme = async () => {
    const t = me.theme === "dark" ? "light" : "dark";
    await api.put("/api/me/preferences", { theme: t });
    setTheme(t);
  };

  let page: JSX.Element;
  let m: Record<string, string> | null;
  const guard = (base: string, el: JSX.Element) => (allowed.has(base) ? el : <NotAuthorized />);
  if (path === "/") page = <Dashboard />;
  else if (path === "/account") page = <Account updates={mode === "local" ? updates : null} />;
  else if (path === "/users") page = guard("/users", <Users />);
  else if (path === "/audit-log") page = guard("/audit-log", <AuditLog />);
  else if (path === "/about") page = <About />;
  else if (path === "/fiscal-years") page = guard("/fiscal-years", <FiscalYears />);
  else if ((m = match("/fiscal-years/:id", path))) page = guard("/fiscal-years", <FiscalYearDetail id={Number(m.id)} />);
  else if (path === "/budgets") page = guard("/budgets", <Budgets />);
  else if (path === "/bank-accounts") page = guard("/bank-accounts", <BankAccounts />);
  else if (path === "/register") page = guard("/register", <Register />);
  else if (path === "/entities") page = guard("/entities", <Entities />);
  else if (path === "/reports") page = guard("/reports", <Reports />);
  else if (path === "/notifications") page = can("reminder.view") ? <Notifications /> : <NotAuthorized />;
  else if (path === "/fundraisers") page = guard("/fundraisers", <Fundraisers />);
  else if (path === "/check-setup") page = guard("/check-setup", <CheckSetup />);
  else if (path === "/payments") page = guard("/payments", <Payments />);
  else if ((m = match("/fundraisers/:id", path))) page = guard("/fundraisers", <FundraiserDetail id={Number(m.id)} />);
  else page = <p>Page not found.</p>;

  return (
    <div className={`shell${collapsed ? " nav-collapsed" : ""}`}>
      <header className="topbar">
        <div className="brand">
          <img className="logo" src="/favicon.svg" alt="" width={20} height={20} /> {workspace} <span className="muted">· PennyWarden</span>
        </div>
        <div className="userbox">
          {/* 1.7.1: the display name (#46), without the roles - they are on My account (#50) */}
          <UpdateIndicator s={updates} />
          <span className="muted user-name">{me.display_name || me.username}</span>
          <button className="small" onClick={toggleTheme} aria-label={`Switch to ${me.theme === "dark" ? "light" : "dark"} mode`}>
            {me.theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
          {can("reminder.view") ? <Bell path={path} /> : null}
          <Link to="/account" className="small-link">My account</Link>
          <button className="small" onClick={logout}>Sign out</button>
        </div>
      </header>
      {warning ? <div className="alert warn banner" role="alert">Security warning: this server is exposed on a network without HTTPS configuration. Deploy behind an HTTPS reverse proxy.</div> : null}
      <SignInNotices notices={me.sign_in_notices || []} onDismissed={() => patchMe({ sign_in_notices: [] })} />
      {can("users.manage") ? <AdminSecurityNotices path={path} /> : null}
      {can("users.manage") ? <BackupFailedBanner path={path} /> : null}
      {mode === "server" && can("users.manage") ? <UpdateBanner s={updates} /> : null}
      <div className="body">
        <nav className="sidenav" aria-label="Main navigation">
          <button type="button" className="nav-toggle" onClick={toggleNav} aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} title={collapsed ? "Expand navigation" : "Collapse navigation"}>
            <span aria-hidden="true">{collapsed ? "»" : "«"}</span>
          </button>
          {nav.map(([to, label]) => (
            <Link key={to} to={to} aria-label={label} title={collapsed ? label : undefined}>
              <NavIcon to={to} /><span className="nav-label">{label}</span>
            </Link>
          ))}
          {can("financial.view") ? null : null}
        </nav>
        <main className="content">{page}</main>
      </div>
    </div>
  );
}

/** v1.6.3 CR-036: notifications bell with the number of due reminders (refreshed on navigation and every 5 min). */
function Bell({ path }: { path: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const load = () => api.get("/api/reminders/count").then((c) => setN(c.due), () => undefined);
    load();
    const t = window.setInterval(load, 5 * 60 * 1000);
    window.addEventListener(REMINDERS_CHANGED, load);
    return () => { window.clearInterval(t); window.removeEventListener(REMINDERS_CHANGED, load); };
  }, [path]);
  return (
    <Link to="/notifications" className="bell" aria-label={n ? `Notifications: ${n} due` : "Notifications"} title="Notifications">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 7H4c0-1 2-2 2-7z" /><path d="M10 20a2 2 0 0 0 4 0" />
      </svg>
      {n ? <span className="bell-count" data-testid="bell-count">{n > 99 ? "99+" : n}</span> : null}
    </Link>
  );
}

function NotAuthorized() {
  return <div className="alert error" role="alert">You are not authorized to view this module.</div>;
}
