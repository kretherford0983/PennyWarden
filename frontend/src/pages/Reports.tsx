// v1.2 CR-002: reporting interface. 2.3.0 (#375): catalog home, a page per report, one registry.
import { Fragment, useEffect, useState } from "react";
import { api, money, qs } from "../api";
import { EntityPicker, ErrorBox, Field, Loading } from "../components";
import { NotAuthorized, useMe } from "../App";
import { Link, useRouter } from "../router";
import BudgetReview, { PlanningSheetReport } from "./BudgetReview";
import FlowReport from "./FlowReport";
import { CountSheetReport, FundraisingFyReport } from "./Fundraisers";
import { currentFy, ReportActions, type ActionsFn, type Links, type RunFn } from "./reports/common";
import { GROUPS, reportPath, searchReports, visibleReports, type ReportDef } from "./reports/registry";
import { SIG_EMPTY, SignatureOptions, signatureProblem, type SigState } from "./SignatureOptions";

/** 2.3.0 (#375): the Reports screen. Home (/reports) is the catalog: every report the user can run, grouped by purpose,
 * with search and Recently run. A report (/reports/<id>) opens on its own page - one header (name, purpose, who it's
 * for, outputs), its options and one action row - with a compact grouped list and a search box on the left to switch
 * reports without going back (Kyle, 2026-10-29: the catalog of layout (a), the report page of (c), the search of (b)).
 * Reports the user can't run (permission or module) are hidden, a report address they can't use is refused, and the
 * user's last options and last 5 runs are remembered server-side (/api/me/report-preferences). */
export default function Reports({ id }: { id?: string }) {
  const { can, me } = useMe();
  const { search } = useRouter();
  const [fys, setFys] = useState<any[] | null>(null);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [prefs, setPrefs] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    Promise.all([api.get("/api/fiscal-years"), api.get("/api/bank-accounts")]).then(([y, a]) => {
      setFys(y);
      setAccounts(a.filter((x: any) => x.register_enabled));
    }, setErr);
    api.get("/api/me/report-preferences").then(setPrefs, () => setPrefs({ recent: [], last: {} }));
  }, []);
  const list = visibleReports({ can, modules: me.modules || {} });
  const def = id ? list.find((r) => r.id === id) : undefined;
  if (id && !def) return <NotAuthorized />;           // #375: an address the user can't use is refused, not just hidden
  if (!fys || !prefs) return <><ErrorBox error={err} /><Loading /></>;
  const onRun = (rid: string): RunFn => (params, label) => {
    api.post("/api/me/report-runs", { report: rid, params, label: label || null }).then(setPrefs, () => undefined);
  };
  if (!def) return <ReportsHome list={list} prefs={prefs} />;
  // a shortcut's or Recently run's options (the address) come before the remembered ones
  const q = new URLSearchParams(search);
  const fromUrl: Record<string, any> = {};
  q.forEach((v, k) => { fromUrl[k] = v === "true" ? true : v === "false" ? false : v; });
  const initial = Object.keys(fromUrl).length ? fromUrl : (prefs.last?.[def.id] || {});
  const props = { fys, accounts, initial, onRun: onRun(def.id), actions: (l: Links) => <ReportActions {...l} /> };
  const Body = BODIES[def.id];
  return (
    <div className="reports-page">
      <ReportSideList list={list} current={def.id} />
      <div className="report-main">
        <header className="report-head">
          <div className="row report-title">
            <h1>{def.name}</h1>
            {def.outputs.map((o) => <span key={o} className="badge output-badge">{o}</span>)}
          </div>
          <p className="report-purpose">{def.purpose}</p>
          <p className="hint">For: {def.audience} · {GROUPS.find((g) => g.id === def.group)?.name}</p>
        </header>
        <section className="card report-body" aria-label={`${def.name} options`}>
          {/* key: a Recently run or another shortcut re-fills the options */}
          <Body key={`${def.id}${search}`} {...props} />
        </section>
      </div>
    </div>
  );
}

type BodyProps = { fys: any[]; accounts: any[]; initial: Record<string, any>; onRun: RunFn; actions: ActionsFn };
const BODIES: Record<string, (p: BodyProps) => JSX.Element> = {
  quarterly: (p) => <PeriodReport {...p} />,
  "fundraising-fy": (p) => <FundraisingFyReport {...p} />,
  audit: (p) => <AuditReport {...p} />,
  close: (p) => <CloseReport {...p} />,
  "fundraiser-detail": (p) => <FundraiserDetailReport {...p} />,
  entity: (p) => <EntityReport {...p} />,
  flow: (p) => <FlowReport accounts={p.accounts} initial={p.initial} onRun={p.onRun} />,
  "budget-review": (p) => <BudgetReview fys={p.fys} initial={p.initial} onRun={p.onRun} />,
  "planning-sheet": (p) => <PlanningSheetReport {...p} />,
  "count-sheet": (p) => <CountSheetReport {...p} />,
};

/** A run's options as an address, so Recently run opens the report with them filled in. */
function runPath(r: any): string {
  const q: Record<string, string> = {};
  Object.entries(r.params || {}).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") q[k] = Array.isArray(v) ? v.join(",") : String(v); });
  return `${reportPath(r.report)}${qs(q)}`;
}

function ReportsHome({ list, prefs }: { list: ReportDef[]; prefs: any }) {
  const [find, setFind] = useState("");
  const shown = searchReports(list, find);
  const recent = (prefs.recent || []).filter((r: any) => list.some((d) => d.id === r.report));
  return (
    <div className="reports-home">
      <div className="page-head no-print">
        <div>
          <h1>Reports</h1>
          <p className="hint">Produce documents to share, audit, analyze or plan. Every report and presentation is here.</p>
        </div>
        <Field label="Find a report"><input type="search" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Search names and descriptions" /></Field>
      </div>
      {recent.length && !find ? (
        <section aria-labelledby="recent-h" className="report-recent" data-testid="recently-run">
          <h2 id="recent-h">Recently run</h2>
          <div className="row">
            {recent.map((r: any, i: number) => {
              const d = list.find((x) => x.id === r.report)!;
              return (
                <Link key={i} to={runPath(r)} className="recent-run">
                  <span className="recent-name">{d.short}</span>
                  {r.label ? <span className="hint">{r.label}</span> : null}
                  <span className="recent-again">Run again →</span>
                </Link>
              );
            })}
          </div>
        </section>
      ) : null}
      {GROUPS.map((g) => {
        const items = shown.filter((r) => r.group === g.id);
        if (!items.length) return null;          // an empty group is hidden
        return (
          <section key={g.id} aria-labelledby={`grp-${g.id}`} className="report-group">
            <h2 id={`grp-${g.id}`}>{g.name} <span className="hint">— {g.why}</span></h2>
            <div className="report-cards">
              {items.map((r) => (
                <Link key={r.id} to={reportPath(r.id)} className="report-card" aria-label={r.name} aria-describedby={`rc-${r.id}`}>
                  <span className="report-card-head"><span className="report-card-name">{r.name}</span><span className="report-card-out">{r.outputs.join(" · ")}</span></span>
                  <span id={`rc-${r.id}`} className="report-card-purpose">{r.purpose}</span>
                  <span className="hint">For: {r.audience}</span>
                </Link>
              ))}
            </div>
          </section>
        );
      })}
      {!shown.length ? <p className="muted">No report matches “{find}”.</p> : null}
      <RestoreReports />
    </div>
  );
}

function ReportSideList({ list, current }: { list: ReportDef[]; current: string }) {
  const [find, setFind] = useState("");
  const shown = searchReports(list, find);
  return (
    <aside className="report-side no-print" aria-label="Reports">
      <Link to="/reports" className="report-back">← All reports</Link>
      <input type="search" aria-label="Find a report" placeholder="Find a report" value={find} onChange={(e) => setFind(e.target.value)} />
      {GROUPS.map((g) => {
        const items = shown.filter((r) => r.group === g.id);
        if (!items.length) return null;
        return (
          <nav key={g.id} aria-label={g.name} className="report-side-group">
            <span className="report-side-h">{g.short}</span>
            {items.map((r) => <Link key={r.id} to={reportPath(r.id)} className={r.id === current ? "current" : ""} aria-label={r.name}>{r.short}</Link>)}
          </nav>
        );
      })}
    </aside>
  );
}

/** 2.0.0 (#124): after a restore, the transactions entered or changed after the backup - to enter them again. Shown
 * only when there are reports. */
function RestoreReports() {
  const [d, setD] = useState<any>(null);
  useEffect(() => { api.get("/api/system/restore-reports").then(setD, () => setD(null)); }, []);
  if (!d?.reports?.length || !d.can_download) return null;
  return (
    <section className="card no-print" aria-labelledby="rr-h">
      <h2 id="rr-h">Restore re-entry reports</h2>
      <p className="hint">When data is restored from a backup, everything entered or changed after the backup was made is listed here (CSV), so it can be
        entered again.</p>
      <table className="table compact">
        <thead><tr><th>Restored</th><th>Backup from</th><th>Transactions</th><th /></tr></thead>
        <tbody>
          {d.reports.map((r: any) => (
            <tr key={r.name}>
              <td>{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</td>
              <td>{r.backup_created_at ? new Date(r.backup_created_at).toLocaleString() : "—"}{r.by_time_only ? " (another system: by time only)" : ""}</td>
              <td>{r.transactions ?? "—"}</td>
              <td><a href={`/api/system/restore-reports/${encodeURIComponent(r.name)}`} download={r.name}>Download CSV</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// v1.3 CR-008: same as the audit report, with the Fiscal Year documents before the budgets and transactions.
function CloseReport({ fys, initial, onRun, actions }: BodyProps) {
  const cur = currentFy(fys);
  const [fy, setFy] = useState(String(initial.fiscal_year_id || (cur ? cur.id : "")));
  const frOn = !!useMe().me.modules?.fundraisers; // v1.6.2 CR-035
  const [fr, setFr] = useState(initial.include_fundraisers !== false);
  const url = (download: boolean) => `/api/reports/fy-close${qs({ fiscal_year_id: fy, download: download || null, include_fundraisers: frOn && !fr ? false : null })}`;
  return (
    <>
      <p>The End of Year Audit report for all accounts (VOID transactions included), with the <b>Fiscal Year documents</b> — approval document, audit signoff and other documents — reproduced right after the Fiscal Year review and before the budgets and transactions. A copy is generated automatically when the Fiscal Year is closed and kept with its documents.</p>
      <div className="report-options">
        <Field label="Fiscal Year">
          <select aria-label="Close report Fiscal Year" value={fy} onChange={(e) => setFy(e.target.value)}>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
          </select>
        </Field>
        {frOn ? <label className="check"><input type="checkbox" checked={fr} onChange={(e) => setFr(e.target.checked)} /> Include fundraisers</label> : null}
      </div>
      {actions({ open: url(false), download: url(true), onRun: () => onRun({ fiscal_year_id: fy, include_fundraisers: fr }, fys.find((y) => String(y.id) === fy)?.display_name || "") })}
    </>
  );
}

function AuditReport({ fys, accounts, initial, onRun, actions }: BodyProps) {
  const cur = currentFy(fys);
  const [f, setF] = useState({ fiscal_year_id: String(initial.fiscal_year_id || (cur ? cur.id : "")), bank_account_id: String(initial.bank_account_id || ""),
    include_void: initial.include_void !== false });
  const [sig, setSig] = useState<SigState>(SIG_EMPTY);
  const frOn = !!useMe().me.modules?.fundraisers; // v1.6.2 CR-035
  const [fr, setFr] = useState(initial.include_fundraisers !== false);
  const sigErr = sig.on ? signatureProblem(sig) : null;
  const url = (download: boolean) => {
    const p = new URLSearchParams(qs({ fiscal_year_id: f.fiscal_year_id, bank_account_id: f.bank_account_id, include_void: f.include_void, download: download || null, include_fundraisers: frOn && fr ? true : null }).slice(1));
    if (sig.on) {
      p.set("signature_page", "true");
      if (sig.choice === "custom") p.set("signature_text", sig.custom);
      else p.set("signature_template_id", sig.choice);
      sig.signers.filter((x) => x.entity_id).forEach((x) => { p.append("signer_id", x.entity_id); p.append("signer_title", x.title.trim()); });
    }
    return `/api/reports/audit?${p.toString()}`;
  };
  // v1.5.0 CR-029: the signature page on its own (same wording and signers)
  const previewUrl = () => {
    const p = new URLSearchParams({ fiscal_year_id: f.fiscal_year_id });
    if (sig.choice === "custom") p.set("signature_text", sig.custom);
    else p.set("signature_template_id", sig.choice);
    sig.signers.filter((x) => x.entity_id).forEach((x) => { p.append("signer_id", x.entity_id); p.append("signer_title", x.title.trim()); });
    return `/api/reports/audit/signature-page?${p.toString()}`;
  };
  return (
    <>
      <p>A printable PDF containing the selected Fiscal Year's budget followed by every transaction in the register for that year with all details, descriptions and notes. Each transaction is <b>immediately followed by its attachments</b> (images and PDF pages), so the printed report keeps every transaction together with its documentation. Fiscal Year documents (approval, audit signoff) are in the Fiscal Year Close report.</p>
      <div className="report-options">
        <Field label="Fiscal Year">
          <select aria-label="Audit report Fiscal Year" value={f.fiscal_year_id} onChange={(e) => setF({ ...f, fiscal_year_id: e.target.value })}>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
          </select>
        </Field>
        <Field label="Account">
          <select value={f.bank_account_id} onChange={(e) => setF({ ...f, bank_account_id: e.target.value })}>
            <option value="">All register accounts</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </Field>
        <label className="check"><input type="checkbox" checked={f.include_void} onChange={(e) => setF({ ...f, include_void: e.target.checked })} /> Include VOID transactions</label>
        {frOn ? <label className="check" title="The Fiscal Year's fundraisers (not archived), after the transactions and before the signature page"><input type="checkbox" checked={fr} onChange={(e) => setFr(e.target.checked)} /> Include fundraisers</label> : null}
      </div>
      <SignatureOptions sig={sig} setSig={setSig} preview={sig.on && !sigErr ? previewUrl() : null} />
      {sigErr ? <div className="alert warn" role="alert">{sigErr}</div> : null}
      {actions({ open: sigErr ? null : url(false), download: sigErr ? null : url(true),
        onRun: () => onRun({ fiscal_year_id: f.fiscal_year_id, bank_account_id: f.bank_account_id, include_void: f.include_void, include_fundraisers: fr },
          `${fys.find((y) => String(y.id) === f.fiscal_year_id)?.display_name || ""} · ${accounts.find((x) => String(x.id) === f.bank_account_id)?.label || "all accounts"}`) })}
      <p className="hint">Large years with many attachments can take a little while to generate. Generating a report is recorded in the audit log.</p>
    </>
  );
}

function EntityReport({ fys, accounts, initial, onRun }: BodyProps) {
  const cur = currentFy(fys);
  const primary = accounts.find((a) => a.is_primary) || accounts[0];
  const [f, setF] = useState({ bank_account_id: initial.bank_account_id !== undefined ? String(initial.bank_account_id) : primary ? String(primary.id) : "",
    date_from: String(initial.date_from || cur?.start_date || ""), date_to: String(initial.date_to || cur?.end_date || ""), entity_id: String(initial.entity_id || ""), details: false });
  const [entities, setEntities] = useState<any[]>([]);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => { api.get("/api/entities?status=all").then(setEntities); }, []);
  const params = { bank_account_id: f.bank_account_id, date_from: f.date_from, date_to: f.date_to, entity_id: f.entity_id, details: true };
  const run = async () => {
    setErr(null);
    try {
      setData(await api.get(`/api/reports/entity-activity${qs(params)}`));
      onRun({ bank_account_id: f.bank_account_id, date_from: f.date_from, date_to: f.date_to, entity_id: f.entity_id },
        `${accounts.find((x) => String(x.id) === f.bank_account_id)?.label || "All accounts"} · ${f.date_from} – ${f.date_to}`);
    } catch (e) { setErr(e); }
  };
  const setFy = (id: string) => {
    const y = fys.find((x) => String(x.id) === id);
    if (y) setF({ ...f, date_from: y.start_date, date_to: y.end_date });
  };
  return (
    <>
      <p className="no-print">How much each entity deposited and withdrew in the selected period for the selected account. Split deposits credit each allocation's entity; transfers between accounts are shown separately and excluded from totals.</p>
      <div className="report-options no-print">
        <Field label="Account">
          <select aria-label="Entity report account" value={f.bank_account_id} onChange={(e) => setF({ ...f, bank_account_id: e.target.value })}>
            <option value="">All register accounts</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </Field>
        <Field label="Fiscal Year (sets dates)">
          <select defaultValue="" onChange={(e) => setFy(e.target.value)}>
            <option value="">—</option>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
          </select>
        </Field>
        <Field label="From"><input type="date" required value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} /></Field>
        <Field label="To"><input type="date" required value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} /></Field>
        <EntityPicker label="Entity (optional)" entities={entities} value={f.entity_id} onChange={(v) => setF({ ...f, entity_id: v })} placeholder="All entities" />
        <button className="primary" onClick={run} disabled={!f.date_from || !f.date_to}>Run report</button>
      </div>
      <ErrorBox error={err} />
      {data ? (
        <div className="entity-report">
          <h2>Entity activity — {data.account ? data.account.label : "All accounts"}</h2>
          <p>{data.date_from} to {data.date_to}</p>
          <div className="actions left no-print">
            <button onClick={() => window.print()}>Print</button>
            <a className="button" href={`/api/reports/entity-activity${qs({ ...params, format: "csv" })}`}>Download CSV</a>
          </div>
          <table className="table">
            <thead><tr><th className="no-print" /><th>Entity</th><th>Entity #</th><th className="num">Deposited</th><th className="num"># Dep.</th><th className="num">Withdrew</th><th className="num"># Wdl.</th><th className="num">Net</th></tr></thead>
            <tbody>
              {data.rows.length === 0 ? <tr><td colSpan={8} className="muted">No activity in this period.</td></tr> : null}
              {data.rows.map((r: any) => (
                <Fragment key={r.key}>
                  <tr className={r.key === "transfers" ? "muted" : ""}>
                    <td className="no-print"><button className="small" aria-expanded={!!open[r.key]} aria-label={`Details for ${r.label}`} onClick={() => setOpen({ ...open, [r.key]: !open[r.key] })}>{open[r.key] ? "▾" : "▸"}</button></td>
                    <td>{r.label}</td><td>{r.entity?.entity_number || ""}</td>
                    <td className="num">{money(r.deposits)}</td><td className="num">{r.deposit_count}</td>
                    <td className="num">{money(r.withdrawals)}</td><td className="num">{r.withdrawal_count}</td>
                    <td className={`num ${Number(r.net) < 0 ? "neg" : ""}`}>{money(r.net)}</td>
                  </tr>
                  {open[r.key] ? (
                    <tr className="detail-row"><td colSpan={8}>
                      <table className="table compact">
                        <thead><tr><th>Txn #</th><th>Date</th><th>Account</th><th>Type</th><th>Description</th><th>Invoice #</th><th>Check #</th><th className="num">Amount</th></tr></thead>
                        <tbody>{r.lines.map((l: any, i: number) => (
                          <tr key={i}><td>{l.transaction_id}</td><td>{l.transaction_date}</td><td>{l.account}</td><td>{l.type}</td><td>{l.description || ""}</td><td>{l.invoice_number || ""}</td><td>{l.check_number || ""}</td><td className="num">{money(l.amount)}</td></tr>
                        ))}</tbody>
                      </table>
                    </td></tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
            <tfoot>
              <tr><th className="no-print" /><th>Total (excluding transfers)</th><th /><th className="num">{money(data.totals.deposits)}</th><th /><th className="num">{money(data.totals.withdrawals)}</th><th /><th className="num">{money(data.totals.net)}</th></tr>
            </tfoot>
          </table>
          <p className="hint">Generated {data.generated_at.replace("T", " ").slice(0, 16)} UTC</p>
        </div>
      ) : null}
    </>
  );
}

/** 2.1.0 (#275): the fundraiser's audit detail (lines, excluded lines, documents and attachments) - what the
 * fundraiser page's report button produced before the stakeholder report. */
function FundraiserDetailReport({ fys, initial, onRun, actions }: BodyProps) {
  const cur = currentFy(fys);
  const [fy, setFy] = useState(String(initial.fiscal_year_id || (cur ? cur.id : "")));
  const [list, setList] = useState<any[]>([]);
  const [fid, setFid] = useState(String(initial.fundraiser_id || ""));
  useEffect(() => {
    if (!fy) return;
    api.get(`/api/fundraisers?fiscal_year_id=${fy}&include_archived=true`).then((r) => {
      setList(r);
      setFid((c) => (r.some((f: any) => String(f.id) === c) ? c : r[0] ? String(r[0].id) : ""));
    }, () => setList([]));
  }, [fy]);
  // 2.1.1 (CodeQL js/xss-through-dom): the links use the id of the fundraiser loaded from the server, never the
  // dropdown's text value
  const sel = list.find((f) => String(f.id) === fid);
  return (
    <>
      <p>One fundraiser's audit detail: its summary, buckets, every transaction line with its budget and transaction number, excluded lines with their reasons, and the fundraiser documents and attachments reproduced. The stakeholder report (without audit detail) is on the fundraiser's page.</p>
      <div className="report-options">
        <Field label="Fiscal Year">
          <select aria-label="Fundraiser detail Fiscal Year" value={fy} onChange={(e) => setFy(e.target.value)}>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
          </select>
        </Field>
        <Field label="Fundraiser">
          <select value={fid} onChange={(e) => setFid(e.target.value)}>
            {list.length ? null : <option value="">No fundraisers in this Fiscal Year</option>}
            {list.map((f) => <option key={f.id} value={f.id}>{f.name}{f.archived ? " (archived)" : ""}</option>)}
          </select>
        </Field>
      </div>
      {actions({ open: sel ? `/api/fundraisers/${sel.id}/report` : null, download: sel ? `/api/fundraisers/${sel.id}/report?download=true` : null,
        onRun: () => onRun({ fiscal_year_id: fy, fundraiser_id: fid }, sel?.name || "") })}
    </>
  );
}

/** 2.3.0 (#373): the Quarterly / Annual Fiscal Year financial report (PDF) and presentation (.pptx) for the board -
 * accounts, cash flow, budgets and fundraisers as of the end of the period. A period still in progress is reported
 * as Preliminary, as of today; a period that hasn't started can't be chosen. */
function PeriodReport({ fys, initial, onRun, actions }: BodyProps) {
  const today = new Date().toISOString().slice(0, 10);
  const cur = currentFy(fys);
  const [fy, setFy] = useState(String(initial.fiscal_year_id || (cur ? cur.id : "")));
  const [opts, setOpts] = useState<any>(null);
  const [period, setPeriod] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (!fy) return;
    setErr(null);
    api.get(`/api/reports/period/options?fiscal_year_id=${fy}`).then((o) => {
      setOpts(o);
      // the latest period that has started: the current quarter (or the year's last one)
      const ok = o.periods.filter((p: any) => p.selectable && p.id !== "ANNUAL");
      const wanted = String(initial.fiscal_year_id || "") === fy && o.periods.find((p: any) => p.id === initial.period && p.selectable);
      setPeriod(wanted ? wanted.id : ok.length ? ok[ok.length - 1].id : (o.periods.find((p: any) => p.selectable)?.id || ""));
    }, setErr);
  }, [fy]);
  const sel = opts?.periods.find((p: any) => p.id === period);
  const url = (format: string, download: boolean) =>
    `/api/reports/period${qs({ fiscal_year_id: fy, period, commentary: note.trim() || null, format: format === "pdf" ? null : format, download: download || null })}`;
  return (
    <>
      <p>The state of the organization's finances for the board: accounts (start and end balances), cash flow by month, budgets
        (the quarter and the year to date, or Q1–Q4 for the year) and fundraisers, with last year's figures beside them when there are
        any. Everything is as of the end of the period; a PDF report and a presentation with charts.</p>
      <ErrorBox error={err} />
      <div className="report-options">
        <Field label="Fiscal Year">
          <select aria-label="Period report Fiscal Year" value={fy} onChange={(e) => setFy(e.target.value)}>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
          </select>
        </Field>
        <Field label="Period">
          <select aria-label="Period" value={period} onChange={(e) => setPeriod(e.target.value)}>
            {(opts?.periods || []).map((p: any) => <option key={p.id} value={p.id} disabled={!p.selectable}>
              {p.label}{p.id !== "ANNUAL" ? ` (${p.start_date} – ${p.end_date})` : ""}{!p.selectable ? " – not started" : ""}</option>)}
          </select>
        </Field>
      </div>
      {sel?.preliminary ? <p className="hint" data-testid="period-preliminary">{sel.id === "ANNUAL" ? "The Fiscal Year has not ended or is not closed yet" : "This quarter has not ended yet"}:
        the report is marked <b>Preliminary</b>, as of {sel.id === "ANNUAL" && today > sel.end_date ? sel.end_date : today}.</p> : null}
      {opts && !opts.prior_fiscal_year ? <p className="hint">No earlier Fiscal Year: the prior-year columns are left out.</p> : null}
      <Field label="Commentary (optional)" hint="Printed on the first page of the report and placed in the presentation's speaker notes.">
        <textarea rows={4} maxLength={opts?.max_commentary || 2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {/* the commentary is free text: not remembered with the options (parameters only) */}
      {actions({ open: sel?.selectable ? url("pdf", false) : null, download: sel?.selectable ? url("pdf", true) : null, pptx: sel?.selectable ? url("pptx", true) : null,
        onRun: () => onRun({ fiscal_year_id: fy, period }, `${fys.find((y) => String(y.id) === fy)?.display_name || ""} · ${period === "ANNUAL" ? "Annual" : period}`) })}
    </>
  );
}
