// v1.2 CR-002: reporting interface.
import { Fragment, useEffect, useState } from "react";
import { api, money, qs } from "../api";
import { EntityPicker, ErrorBox, Field, Loading } from "../components";
import { useMe } from "../App";
import BudgetPrep from "./BudgetPrep";
import FlowReport from "./FlowReport";
import { SIG_EMPTY, SignatureOptions, signatureProblem, type SigState } from "./SignatureOptions";

export default function Reports() {
  const [tab, setTab] = useState<"audit" | "close" | "entity" | "flow" | "prep" | "frdetail">("audit");
  const { can, me } = useMe();
  const [fys, setFys] = useState<any[] | null>(null);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    Promise.all([api.get("/api/fiscal-years"), api.get("/api/bank-accounts")]).then(([y, a]) => {
      setFys(y);
      setAccounts(a.filter((x: any) => x.register_enabled));
    }, setErr);
  }, []);
  if (!fys) return <><ErrorBox error={err} /><Loading /></>;
  return (
    <div>
      <div className="page-head no-print">
        <h1>Reports</h1>
        <div role="tablist" className="row">
          <button role="tab" aria-selected={tab === "audit"} className={tab === "audit" ? "primary" : ""} onClick={() => setTab("audit")}>End of Year Audit</button>
          <button role="tab" aria-selected={tab === "close"} className={tab === "close" ? "primary" : ""} onClick={() => setTab("close")}>Fiscal Year Close</button>
          <button role="tab" aria-selected={tab === "entity"} className={tab === "entity" ? "primary" : ""} onClick={() => setTab("entity")}>Entity activity</button>
          <button role="tab" aria-selected={tab === "flow"} className={tab === "flow" ? "primary" : ""} onClick={() => setTab("flow")}>Financial Flow</button>
          {me.modules?.fundraisers ? <button role="tab" aria-selected={tab === "frdetail"} className={tab === "frdetail" ? "primary" : ""} onClick={() => setTab("frdetail")}>Fundraiser detail (audit)</button> : null}
          {can("budget.manage") ? <button role="tab" aria-selected={tab === "prep"} className={tab === "prep" ? "primary" : ""} onClick={() => setTab("prep")}>Budget Prep</button> : null}
        </div>
      </div>
      {tab === "audit" ? <AuditReport fys={fys} accounts={accounts} /> : null}
      {tab === "close" ? <CloseReport fys={fys} /> : null}
      {tab === "entity" ? <EntityReport fys={fys} accounts={accounts} /> : null}
      {tab === "flow" ? <FlowReport accounts={accounts} /> : null}
      {tab === "prep" && can("budget.manage") ? <BudgetPrep fys={fys} /> : null}
      {tab === "frdetail" ? <FundraiserDetailReport fys={fys} /> : null}
      <RestoreReports />
    </div>
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
function CloseReport({ fys }: { fys: any[] }) {
  const today = new Date().toISOString().slice(0, 10);
  const cur = fys.find((f) => f.start_date <= today && f.end_date >= today) || fys[fys.length - 1];
  const [fy, setFy] = useState(cur ? String(cur.id) : "");
  const frOn = !!useMe().me.modules?.fundraisers; // v1.6.2 CR-035
  const [fr, setFr] = useState(true);
  const url = (download: boolean) => `/api/reports/fy-close${qs({ fiscal_year_id: fy, download: download || null, include_fundraisers: frOn && !fr ? false : null })}`;
  return (
    <section className="card">
      <h2>Fiscal Year Close report</h2>
      <p>The End of Year Audit report for all accounts (VOID transactions included), with the <b>Fiscal Year documents</b> — approval document, audit signoff and other documents — reproduced right after the Fiscal Year review and before the budgets and transactions. A copy is generated automatically when the Fiscal Year is closed and kept with its documents.</p>
      <div className="report-options">
        <Field label="Fiscal Year">
          <select aria-label="Close report Fiscal Year" value={fy} onChange={(e) => setFy(e.target.value)}>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
          </select>
        </Field>
        {frOn ? <label className="check"><input type="checkbox" checked={fr} onChange={(e) => setFr(e.target.checked)} /> Include fundraisers</label> : null}
      </div>
      <div className="actions left">
        <a className="button primary" href={url(false)} target="_blank" rel="noopener">Open Close report PDF</a>
        <a className="button" href={url(true)}>Download PDF</a>
      </div>
    </section>
  );
}

function AuditReport({ fys, accounts }: { fys: any[]; accounts: any[] }) {
  const today = new Date().toISOString().slice(0, 10);
  const cur = fys.find((f) => f.start_date <= today && f.end_date >= today) || fys[fys.length - 1];
  const [f, setF] = useState({ fiscal_year_id: cur ? String(cur.id) : "", bank_account_id: "", include_void: true });
  const [sig, setSig] = useState<SigState>(SIG_EMPTY);
  const frOn = !!useMe().me.modules?.fundraisers; // v1.6.2 CR-035
  const [fr, setFr] = useState(true);
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
    <section className="card">
      <h2>End of Year Audit report</h2>
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
      <div className="actions left">
        {sigErr ? (
          <><button className="primary" disabled>Open printable PDF</button><button disabled>Download PDF</button></>
        ) : (
          <><a className="button primary" href={url(false)} target="_blank" rel="noopener">Open printable PDF</a>
          <a className="button" href={url(true)}>Download PDF</a></>
        )}
      </div>
      <p className="hint">Large years with many attachments can take a little while to generate. Generating a report is recorded in the audit log.</p>
    </section>
  );
}

function EntityReport({ fys, accounts }: { fys: any[]; accounts: any[] }) {
  const today = new Date().toISOString().slice(0, 10);
  const cur = fys.find((f) => f.start_date <= today && f.end_date >= today) || fys[fys.length - 1];
  const primary = accounts.find((a) => a.is_primary) || accounts[0];
  const [f, setF] = useState({ bank_account_id: primary ? String(primary.id) : "", date_from: cur?.start_date || "", date_to: cur?.end_date || "", entity_id: "", details: false });
  const [entities, setEntities] = useState<any[]>([]);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => { api.get("/api/entities?status=all").then(setEntities); }, []);
  const params = { bank_account_id: f.bank_account_id, date_from: f.date_from, date_to: f.date_to, entity_id: f.entity_id, details: true };
  const run = async () => {
    setErr(null);
    try { setData(await api.get(`/api/reports/entity-activity${qs(params)}`)); } catch (e) { setErr(e); }
  };
  const setFy = (id: string) => {
    const y = fys.find((x) => String(x.id) === id);
    if (y) setF({ ...f, date_from: y.start_date, date_to: y.end_date });
  };
  return (
    <section className="card">
      <h2 className="no-print">Entity activity report</h2>
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
    </section>
  );
}

/** 2.1.0 (#275): the fundraiser's audit detail (lines, excluded lines, documents and attachments) - what the
 * fundraiser page's report button produced before the stakeholder report. */
function FundraiserDetailReport({ fys }: { fys: any[] }) {
  const today = new Date().toISOString().slice(0, 10);
  const cur = fys.find((f) => f.start_date <= today && f.end_date >= today) || fys[fys.length - 1];
  const [fy, setFy] = useState(cur ? String(cur.id) : "");
  const [list, setList] = useState<any[]>([]);
  const [fid, setFid] = useState("");
  useEffect(() => {
    if (!fy) return;
    api.get(`/api/fundraisers?fiscal_year_id=${fy}&include_archived=true`).then((r) => { setList(r); setFid(r[0] ? String(r[0].id) : ""); }, () => setList([]));
  }, [fy]);
  return (
    <section className="card">
      <h2>Fundraiser detail (audit)</h2>
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
      <div className="actions left">
        {fid ? <><a className="button primary" href={`/api/fundraisers/${fid}/report`} target="_blank" rel="noopener">Open detail PDF</a>
          <a className="button" href={`/api/fundraisers/${fid}/report?download=true`}>Download PDF</a></>
          : <button className="primary" disabled>Open detail PDF</button>}
      </div>
    </section>
  );
}
