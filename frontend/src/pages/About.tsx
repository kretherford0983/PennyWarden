import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { api } from "../api";
import { BuildDetails, ErrorBox, Loading } from "../components";
import { useRouter } from "../router";
import { BackupRestore } from "./BackupRestore";
import { UpdateSettings } from "./Updates";
import { useMe } from "../App";
import { MaintenancePanel } from "./Maintenance";
import { ReinitializePanel } from "./Reinitialize";
import { TestingPanel } from "./Testing";
import { BackupWarningSetting, DiagnosticsPanel, HealthPanel, OrganizationPanel, SecurityOverviewPanel, SessionsPanel, SettingsPanel } from "./AdminSettings";

/** 2.0.0 build 11 (#216, docs/ui-standards.md): System/About in tabs, each at its own address (/about/<tab>, so it can
 * be bookmarked, reloaded and reached with Back). Tabs the user can't use are not shown; an unknown or unavailable tab
 * address shows About. */
export const ABOUT_TABS = [
  ["about", "About"], ["general", "General"], ["settings", "Settings"], ["backups", "Backups"],
  ["security", "Security"], ["health", "System health"], ["advanced", "Advanced"], ["testing", "Testing"],
] as const;
export type AboutTab = (typeof ABOUT_TABS)[number][0];
export const aboutPath = (tab: AboutTab) => (tab === "about" ? "/about" : `/about/${tab}`);

export default function About() {
  const { can } = useMe();
  const { path, navigate } = useRouter();
  const [a, setA] = useState<any>(null);
  const [org, setOrg] = useState<string | null>(null);
  const [testingMode, setTestingMode] = useState(false);   // 2.2.0 (#231)
  useEffect(() => {
    api.get("/api/system/about").then(setA);
    api.get("/api/system/status").then((s) => { setOrg(s.workspace_name); setTestingMode(!!s.testing_mode); });
  }, []);
  const admin = can("system.manage");
  const viewer = can("system.view");                  // Administrators and Auditors
  const backups = !!a && a.restore_max_mb != null;     // the backup/restore permission (the server says)
  const allowed: Record<AboutTab, boolean> = {
    about: true, general: admin, settings: viewer, backups: backups || admin, security: viewer, health: admin,
    advanced: admin || backups, testing: admin && testingMode,
  };
  const asked = (path.split("/")[2] || "about") as AboutTab;
  const known = ABOUT_TABS.some(([k]) => k === asked);
  const tab: AboutTab = known && allowed[asked] ? asked : "about";
  useEffect(() => {   // a tab address this user can't use (or a typo) becomes /about
    if (a && org !== null && path !== aboutPath(tab) && path.startsWith("/about")) navigate(aboutPath(tab), { replace: true });
  }, [a, org, path, tab]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!a) return <Loading />;
  const tabs = ABOUT_TABS.filter(([k]) => allowed[k]);
  const panels: Record<AboutTab, () => ReactNode> = {
    about: () => (
      <>
        <BuildDetails info={a} />
        {a.bind_host ? <dl className="dl"><dt>Bind address</dt><dd>{a.bind_host}:{a.port}</dd></dl> : null}
        {a.insecure_transport_warning ? <div className="alert warn">Network deployment without HTTPS configuration is not secure.</div> : null}
        <div className="alert warn" role="note"><strong>Data protection:</strong> {a.backup_notice}</div>
        {backups ? <UpdateSettings /> : null}
      </>
    ),
    general: () => (
      <>
        {org != null ? <OrganizationPanel name={org} onRenamed={(n) => { setOrg(n); window.dispatchEvent(new CustomEvent("pw:workspace-renamed", { detail: n })); }} /> : null}
        <ModulesPanel />
      </>
    ),
    settings: () => <SettingsPanel />,
    backups: () => (
      <>
        {backups ? <BackupRestore maxMb={a.restore_max_mb} /> : null}
        {admin ? <section className="card" aria-labelledby="backup-age-h"><h2 id="backup-age-h">Backup reminder</h2><BackupWarningSetting /></section> : null}
      </>
    ),
    security: () => <><SecurityOverviewPanel /><SessionsPanel /></>,
    health: () => <><HealthPanel /><DiagnosticsPanel /></>,
    advanced: () => <>{admin ? <MaintenancePanel /> : null}{backups ? <ReinitializePanel /> : null}</>,
    testing: () => <TestingPanel />,
  };
  return (
    <div>
      <h1>System / About</h1>
      {tabs.length > 1 ? <PageTabs label="System/About sections" tabs={tabs} current={tab} onSelect={(k) => navigate(aboutPath(k))} /> : null}
      <div role={tabs.length > 1 ? "tabpanel" : undefined} id={`about-panel`} aria-labelledby={tabs.length > 1 ? `about-tab-${tab}` : undefined}
           data-testid={`about-${tab}`} key={tab}>
        {panels[tab]()}
      </div>
    </div>
  );
}

/** #216: a page's tab bar (WAI-ARIA tabs, automatic activation): ←/→ move between tabs and open them, Home/End go to
 * the first/last. The caller keeps the open tab in the address. */
export function PageTabs<K extends string>({ label, tabs, current, onSelect }: {
  label: string; tabs: readonly (readonly [K, string])[]; current: K; onSelect: (k: K) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const go = (i: number) => {
    const n = (i + tabs.length) % tabs.length;
    onSelect(tabs[n][0]);
    requestAnimationFrame(() => ref.current?.querySelectorAll<HTMLButtonElement>("[role=tab]")[n]?.focus());
  };
  const onKey = (e: KeyboardEvent) => {
    const i = tabs.findIndex(([k]) => k === current);
    if (e.key === "ArrowRight") { e.preventDefault(); go(i + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(i - 1); }
    else if (e.key === "Home") { e.preventDefault(); go(0); }
    else if (e.key === "End") { e.preventDefault(); go(tabs.length - 1); }
  };
  return (
    <div className="page-tabs" role="tablist" aria-label={label} ref={ref} onKeyDown={onKey}>
      {tabs.map(([k, l]) => (
        <button key={k} type="button" role="tab" id={`about-tab-${k}`} aria-selected={k === current} aria-controls="about-panel"
                tabIndex={k === current ? 0 : -1} className={k === current ? "current" : ""} onClick={() => onSelect(k)}>{l}</button>
      ))}
    </div>
  );
}

/** v1.6.0 CR-033: optional modules, switched on/off by an Administrator (data is kept when a module is off). */
function ModulesPanel() {
  const [m, setM] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.get("/api/system/modules").then(setM, setErr); }, []);
  const toggle = async (key: "fundraisers" | "checks" | "donations", on: boolean) => {
    setErr(null);
    setSaved(false);
    const before = m;
    setM({ ...m, [key]: on }); // shown at once; reverted if saving fails
    try { setM(await api.put("/api/system/modules", { [key]: on })); setSaved(true); } catch (x) { setM(before); setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="modules-h">
      <h2 id="modules-h">Optional modules</h2>
      <ErrorBox error={err} />
      {m ? (
        <>
          <label className="check"><input type="checkbox" checked={m.fundraisers} onChange={(e) => toggle("fundraisers", e.target.checked)} /> Fundraiser module</label>
          <p className="hint">Adds <b>Fundraisers</b> to the menu of Budget Managers, Budget Users, Register Users and Auditors (it appears at their next sign-in or page reload).
            Turning it off hides the module; fundraisers that were set up are kept.</p>
          <label className="check"><input type="checkbox" checked={!!m.checks} onChange={(e) => toggle("checks", e.target.checked)} /> Payments module</label>
          <p className="hint">Check printing, payments, cover letters and envelopes. Adds <b>Payments Setup</b> to the Administrator's menu (check styles,
            signatures, letter and envelope templates, test prints), and <b>Payments</b> and a <b>Print check</b> action on withdrawals for Register Users. For
            printable check stock that already carries the bank numbers. Turning it off hides the module; settings are kept.</p>
          {/* 2.1.0 (#312) */}
          <label className="check"><input type="checkbox" checked={!!m.donations} onChange={(e) => toggle("donations", e.target.checked)} /> Donations module</label>
          <p className="hint">Donation receipt letters. Adds <b>Donations Setup</b> to the Administrator's menu (EIN, mailing address, receipt letter, test
            print), and a <b>Donation receipt</b> action on deposits in the register: Register Users mark donations and print receipts; Budget Managers,
            Budget Users and Auditors see them. Works with the Payments module on or off. Turning it off hides the module; receipts and settings are kept.</p>
          {saved ? <p className="hint" role="status">Saved.</p> : null}
        </>
      ) : null}
    </section>
  );
}
