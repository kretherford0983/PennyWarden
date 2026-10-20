// v1.6.0 CR-033: Fundraiser module - list per Fiscal Year (+ upcoming), details, create/edit (Budget Manager).
import { Fragment, lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { api, money, todayIso } from "../api";
import { Attachments, EntityPicker, ErrorBox, Field, GuardedForm, Loading, Modal, RowMenu } from "../components";
import { positionTitle } from "./SignatureOptions";
import { Link, useRouter } from "../router";
import { useMe } from "../App";

const FundraiserCharts = lazy(() => import("./FundraiserCharts")); // chart library loaded on demand

const STATUS: Record<string, string> = { PLANNED: "Planned", IN_PROGRESS: "In progress", ENDED: "Ended", ARCHIVED: "Archived", CANCELLED: "Cancelled" };
const UPCOMING = "upcoming";

export function FundraiserStatus({ status }: { status: string }) {
  return <span className={`pill pill-fr-${status.toLowerCase()}`}>{STATUS[status] || status}</span>;
}

const eventDates = (f: any) => (f.start_date === f.end_date ? f.start_date : `${f.start_date} – ${f.end_date}`);
const roiText = (r: string | null) => (r === null ? "—" : `${(Number(r) * 100).toFixed(1)}%`);

// ------------------------------------------------------------------ list
export default function Fundraisers() {
  const { can } = useMe();
  const { navigate } = useRouter();
  const [fys, setFys] = useState<any[] | null>(null);
  const [fy, setFy] = useState("");
  const [archived, setArchived] = useState(false);
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());   // 2.1.0 (#277): the Fiscal Year report's fundraisers
  const [fyReport, setFyReport] = useState(false);

  useEffect(() => {
    Promise.all([api.get("/api/fiscal-years"), api.get(`/api/fiscal-years/natural?date=${todayIso()}`)]).then(([y, nat]) => {
      setFys(y);
      setFy(nat.default_fiscal_year_id ? String(nat.default_fiscal_year_id) : y.length ? String(y[y.length - 1].id) : UPCOMING);
    }, setErr);
  }, []);
  useEffect(() => {
    if (!fy) return;
    setRows(null);
    const q = fy === UPCOMING ? "upcoming=true" : `fiscal_year_id=${fy}`;
    api.get(`/api/fundraisers?${q}${archived ? "&include_archived=true" : ""}`).then(setRows, setErr);
    if (fy !== UPCOMING) api.get(`/api/fundraisers/fy-report/selection?fiscal_year_id=${fy}`).then((x) => setPicked(new Set(x.default_ids)), () => setPicked(new Set()));
  }, [fy, archived]);
  const toggle = (id: number) => { const n = new Set(picked); if (n.has(id)) n.delete(id); else n.add(id); setPicked(n); };
  const shown = (rows || []).filter((r) => picked.has(r.id));

  if (!fys) return <><ErrorBox error={err} /><Loading /></>;
  return (
    <div>
      <div className="page-head">
        <h1>Fundraisers</h1>
        <Field label="Fiscal Year">
          <select aria-label="Fundraisers Fiscal Year" value={fy} onChange={(e) => setFy(e.target.value)}>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
            <option value={UPCOMING}>Upcoming — no Fiscal Year yet</option>
          </select>
        </Field>
        <label className="check"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived</label>
        {fy !== UPCOMING && rows?.length ? <button onClick={() => setFyReport(true)} disabled={!shown.length}>Fiscal Year report…</button> : null}
        {can("fundraiser.manage") ? <Link className="button" to="/fundraiser-series">Fundraiser series</Link> : null}
        {can("fundraiser.manage") ? <button className="primary" onClick={() => setCreating(true)}>New fundraiser</button> : null}
      </div>
      <ErrorBox error={err} />
      {!rows ? <Loading /> : !rows.length ? (
        <p className="muted">{fy === UPCOMING ? "No fundraisers for events beyond the Fiscal Years set up so far." : "No fundraisers in this Fiscal Year."}</p>
      ) : (
        <table className="table" data-testid="fundraiser-list">
          <thead><tr>{fy !== UPCOMING ? <th><span className="sr-only">In the report</span>
            <button className="small" onClick={() => setPicked(new Set(rows.map((r) => r.id)))}>All</button> <button className="small" onClick={() => setPicked(new Set())}>None</button></th> : null}<th>Fundraiser</th><th>Event</th><th>Status</th><th>Fiscal Years</th><th className="num">Income</th><th className="num">Expenses</th><th className="num">Net</th></tr></thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.id}>
                {fy !== UPCOMING ? <td><input type="checkbox" aria-label={`Include ${f.name} in the Fiscal Year report`} checked={picked.has(f.id)} onChange={() => toggle(f.id)} /></td> : null}
                <td><Link to={`/fundraisers/${f.id}`}>{f.name}</Link></td>
                <td>{eventDates(f)}</td>
                <td><FundraiserStatus status={f.status} /></td>
                <td>{f.fiscal_years.length ? f.fiscal_years.map((y: any) => y.display_name).join(" – ") : <span className="muted">No budgets yet</span>}</td>
                <td className="num">{money(f.income)}</td>
                <td className="num">{money(f.expense)}</td>
                <td className={`num ${Number(f.net) < 0 ? "neg" : ""}`}>{money(f.net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {creating ? <FundraiserForm onClose={() => setCreating(false)} onSaved={(f) => navigate(`/fundraisers/${f.id}`)} /> : null}
      {fyReport ? <FyReportDialog fy={fys.find((y) => String(y.id) === fy)} ids={shown.map((r) => r.id)} manage={can("fundraiser.manage")} onClose={() => setFyReport(false)} /> : null}
    </div>
  );
}

// 2.1.0 (#277): the Fiscal Year fundraising report and presentation for the ticked fundraisers
function FyReportDialog({ fy, ids, manage, onClose }: { fy: any; ids: number[]; manage: boolean; onClose: () => void }) {
  const [o, setO] = useState({ years: "5", targeted: false, avg_years: "5" });
  const [notes, setNotes] = useState("");
  const [savedNotes, setSavedNotes] = useState("");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get(`/api/fundraisers/fy-report/selection?fiscal_year_id=${fy.id}`).then((x) => { setNotes(x.notes || ""); setSavedNotes(x.notes || ""); }, setErr); }, [fy.id]);
  const href = (format: string) => {
    const p = new URLSearchParams({ fiscal_year_id: String(fy.id), years: o.years, targeted: String(o.targeted), avg_years: o.avg_years, format });
    ids.forEach((i) => p.append("ids", String(i)));
    return `/api/fundraisers/fy-report?${p.toString()}`;
  };
  const saveNotes = async () => {
    setErr(null);
    try { const r = await api.put("/api/fundraisers/fy-report/notes", { fiscal_year_id: fy.id, notes }); setNotes(r.notes || ""); setSavedNotes(r.notes || ""); } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Fiscal Year fundraising report" onClose={onClose} wide>
      <p>{ids.length} fundraiser{ids.length === 1 ? "" : "s"} of <b>{fy.display_name}</b>, with the history of their series (linked with <i>Continues from</i>, plus results entered for earlier years). No contributor names.</p>
      <ErrorBox error={err} />
      <div className="row fields">
        <Field label="Years of history">
          <select value={o.years} onChange={(e) => setO({ ...o, years: e.target.value })}>
            {[2, 3, 4, 5, 7, 10].map((n) => <option key={n} value={n}>{n}</option>)}
            <option value="-1">All available</option>
          </select>
        </Field>
        <label className="check"><input type="checkbox" checked={o.targeted} onChange={(e) => setO({ ...o, targeted: e.target.checked })} /> Include targeted total</label>
        {o.targeted ? <Field label="Average of the last … active years"><input type="number" min={1} max={20} value={o.avg_years} onChange={(e) => setO({ ...o, avg_years: e.target.value })} /></Field> : null}
      </div>
      {o.targeted ? <p className="hint">The targeted total adds, for each series that has not held its event yet this year, the average of its last {o.avg_years} active years — shown as a separate estimate.</p> : null}
      {manage ? (
        <>
          <Field label="Notes (printed on the report and deck; remembered for this Fiscal Year)">
            <textarea rows={3} maxLength={10000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Additional revenue expected from a matching-gift program" />
          </Field>
          <div className="actions left"><button disabled={notes === savedNotes} onClick={saveNotes}>Save notes</button></div>
        </>
      ) : savedNotes ? <p className="pre-wrap"><b>Notes:</b> {savedNotes}</p> : null}
      <div className="actions">
        <button onClick={onClose}>Done</button>
        <a className="button" href={href("pptx")}>Presentation</a>
        <a className="button primary" href={href("pdf")} target="_blank" rel="noopener">Report (PDF)</a>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ details
export function FundraiserDetail({ id }: { id: number }) {
  const { me, can } = useMe();
  const { navigate } = useRouter();
  const [f, setF] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [lineEdit, setLineEdit] = useState<any>(null); // v1.6.1 CR-034
  const [bucketEdit, setBucketEdit] = useState<any>(null);
  const [categoryEdit, setCategoryEdit] = useState<any>(null);   // 2.1.0 (#278)
  const [ordering, setOrdering] = useState(false);
  const [reporting, setReporting] = useState(false);   // 2.1.0 (#275)
  const [nextYear, setNextYear] = useState<any>(null);  // 2.1.0 (#277)
  const [linking, setLinking] = useState(false);
  const [cancelling, setCancelling] = useState(false); // v1.6.4 CR-037
  const [countSheet, setCountSheet] = useState(false); // v1.6.4 CR-038
  const load = () => api.get(`/api/fundraisers/${id}`).then(setF, setErr);
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!f) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const manage = can("fundraiser.manage");
  const canLines = can("fundraiser.lines") && !f.read_only; // Budget Manager / Register User
  const canArrange = can("fundraiser.lines"); // 2.1.0 (#278): categories and order are presentation only (closed years too)
  const bucketName = (bid: number) => f.buckets.items.find((b: any) => b.id === bid)?.name || "?";
  const act = async (fn: () => Promise<any>) => {
    setErr(null);
    try { await fn(); } catch (x) { setErr(x); }
  };
  const t = f.totals;
  const attachments = f.lines.flatMap((l: any) => l.attachments.map((a: any) => ({ ...a, line: l })));
  return (
    <div className="fundraiser">
      <p><Link to="/fundraisers">← Fundraisers</Link></p>
      <div className="page-head">
        <h1>{f.name} <FundraiserStatus status={f.status} /></h1>
        <button onClick={() => setReporting(true)}>Report…</button>
        <button onClick={() => setCountSheet(true)}>Cash count sheet…</button>
        {manage ? (
          <div className="row">
            {!f.read_only ? <button onClick={() => setEditing(true)}>Edit</button> : null}
            {f.archived
              ? <button onClick={() => act(async () => setF(await api.post(`/api/fundraisers/${id}/restore`)))}>Restore</button>
              : <button onClick={() => act(async () => setF(await api.post(`/api/fundraisers/${id}/archive`)))}>Archive</button>}
            {f.read_only ? null : f.cancelled
              ? <button onClick={() => act(async () => setF(await api.post(`/api/fundraisers/${id}/reinstate`)))}>Reinstate</button>
              : <button onClick={() => setCancelling(true)}>Mark as cancelled…</button>}
            <button onClick={() => act(async () => setNextYear({ ...(await api.get(`/api/fundraisers/${id}/next-year`)), from_name: f.name }))}>Create next year's…</button>
            <button className="danger" onClick={() => setConfirmDelete(true)}>Delete…</button>
          </div>
        ) : null}
      </div>
      <dl className="dl">
        <dt>Event</dt><dd data-testid="fr-event">{eventDates(f)}</dd>
        <dt>Fiscal Years</dt><dd>{f.fiscal_years.length ? f.fiscal_years.map((y: any) => y.display_name).join(" – ") : "—"}</dd>
        <dt>Series</dt><dd data-testid="fr-series">{f.series_link.series
          ? <>{f.series_link.series.name}{f.series_link.continues_from ? <> — continues <Link to={`/fundraisers/${f.series_link.continues_from.id}`}>{f.series_link.continues_from.name}</Link></> : null}</>
          : <span className="muted">Not linked to an earlier year</span>}
          {manage ? <button className="small fr-final-btn" onClick={() => setLinking(true)}>Change…</button> : null}</dd>
        {f.description ? <><dt>Description</dt><dd className="pre-wrap">{f.description}</dd></> : null}
        {f.filter_text ? <><dt>Description filter</dt><dd><code>{f.filter_text}</code>{f.filter_regex ? " (regular expression)" : " (contains, any case)"}</dd></> : null}
      </dl>
      <ErrorBox error={err} />
      {f.cancelled ? <div className="alert error" role="note" data-testid="fr-cancelled"><b>Cancelled</b> — this fundraiser did not take place as planned. Reason: {f.cancel_reason} <span className="muted">({String(f.cancelled_at).slice(0, 10)})</span>. Its transactions are still listed and counted below.</div> : null}
      {f.read_only ? <div className="alert info" role="note">The Fiscal Year of this fundraiser is closed; it can no longer be changed.</div> : null}
      {f.notices.length ? (
        <ul className="notices" aria-label="Notices">
          {f.notices.map((n: any, i: number) => <li key={i} className={`alert ${n.code === "NO_BUDGETS" || n.code === "FUTURE_FY" || n.code === "FY_WITHOUT_BUDGET" ? "info" : "warn"}`} data-code={n.code}>{n.message}</li>)}
        </ul>
      ) : null}

      <section className="card">
        <h2>Budgets</h2>
        {f.budgets.length ? (
          <table className="table compact">
            <thead><tr><th>Fiscal Year</th><th>Kind</th><th>Budget</th></tr></thead>
            <tbody>{f.budgets.map((b: any) => <tr key={b.id}><td>{b.fiscal_year.display_name}</td><td>{b.kind === "INCOME" ? "Income" : "Expense"}</td><td>{b.label}</td></tr>)}</tbody>
          </table>
        ) : <p className="muted">No budgets selected yet.</p>}
      </section>

      <div className="tiles" data-testid="fr-totals">
        <div className="tile"><div className="tile-label">Income</div><div className="tile-value">{money(t.income)}</div></div>
        <div className="tile"><div className="tile-label">Expenses</div><div className="tile-value">{money(t.expense)}</div></div>
        <div className="tile"><div className="tile-label">Net</div><div className={`tile-value ${Number(t.net) < 0 ? "neg" : ""}`}>{money(t.net)}</div></div>
        <div className="tile"><div className="tile-label">Return on expenses (net ÷ expenses)</div><div className="tile-value">{roiText(t.roi)}</div></div>
      </div>
      {Number(t.cash_float_out) || Number(t.cash_float_returned) || t.excluded_lines ? (
        <p className="hint" data-testid="fr-adjustments">
          Not counted above:
          {Number(t.cash_float_out) ? ` cash float taken out ${money(t.cash_float_out)};` : ""}
          {Number(t.cash_float_returned) ? ` cash float returned ${money(t.cash_float_returned)};` : ""}
          {t.excluded_lines ? ` ${t.excluded_lines} excluded line${t.excluded_lines === 1 ? "" : "s"} (income ${money(t.excluded_income)}, expenses ${money(t.excluded_expense)}).` : ""}
        </p>
      ) : null}

      <StakeholderReport f={f} manage={manage} onChanged={setF} onOpen={() => setReporting(true)} />

      <section className="card" aria-labelledby="fr-buckets-h">
        <div className="charts-head">
          <h2 id="fr-buckets-h">Buckets</h2>
          <div className="row">
            {canLines ? <button className="small" onClick={() => setBucketEdit({})}>New bucket</button> : null}
            {canArrange ? <button className="small" onClick={() => setCategoryEdit({})}>New category</button> : null}
            {canArrange && (f.buckets.items.length > 1 || f.buckets.categories.length > 1) ? <button className="small" onClick={() => setOrdering(true)}>Reorder…</button> : null}
          </div>
        </div>
        <p className="hint">Buckets break the fundraiser down by offering (for example food sales or a raffle). A bucket can hold income and expenses. Group buckets under optional <b>categories</b> (for example Sponsorships or Day-of event). Assign amounts of transaction lines to them with <b>Manage</b> in the transaction list.</p>
        {f.buckets.items.length || f.buckets.categories.length ? (
          <BucketTable f={f} canLines={canLines} canArrange={canArrange} onEdit={setBucketEdit} onEditCategory={setCategoryEdit}
            onDelete={(b: any) => window.confirm(`Delete the bucket “${b.name}”? Its lines become unassigned.`) && act(async () => setF(await api.delete(`/api/fundraisers/${id}/buckets/${b.id}`)))}
            onDeleteCategory={(c: any) => window.confirm(`Delete the category “${c.name}”? Its buckets stay, uncategorized; no figures change.`) && act(async () => setF(await api.delete(`/api/fundraisers/${id}/categories/${c.id}`)))} />
        ) : <p className="muted">No buckets yet.</p>}
      </section>

      {f.per_fiscal_year.length > 1 ? (
        <section className="card">
          <h2>By Fiscal Year</h2>
          <table className="table compact">
            <thead><tr><th>Fiscal Year</th><th className="num">Income</th><th className="num">Expenses</th><th className="num">Net</th></tr></thead>
            <tbody>{f.per_fiscal_year.map((p: any) => (
              <tr key={p.fiscal_year.id}><td>{p.fiscal_year.display_name}{p.read_only ? <span className="muted"> (closed)</span> : null}</td><td className="num">{money(p.income)}</td><td className="num">{money(p.expense)}</td><td className="num">{money(p.net)}</td></tr>
            ))}</tbody>
            <tfoot><tr className="total-row"><th>Total</th><th className="num">{money(t.income)}</th><th className="num">{money(t.expense)}</th><th className="num">{money(t.net)}</th></tr></tfoot>
          </table>
        </section>
      ) : null}

      {f.lines.length ? (
        <Suspense fallback={<p className="hint">Loading charts…</p>}>
          <FundraiserCharts f={f} theme={me.theme === "dark" ? "dark" : "light"} />
        </Suspense>
      ) : null}

      <section className="card">
        <h2>Transactions</h2>
        <p className="hint">Every active line allocated to the selected budgets{f.filter_text ? " whose description matches the filter" : ""}, whatever its date. Transactions are entered in the Register.
          {f.filtered_out_lines ? ` ${f.filtered_out_lines} line${f.filtered_out_lines === 1 ? "" : "s"} in these budgets did not match the filter.` : ""}</p>
        {f.lines.length ? (
          <div className="table-scroll">
            <table className="table fr-lines" data-testid="fr-lines">
              <thead><tr><th>Date</th><th>Type</th><th>Account</th><th>Entity</th><th>Description</th><th>Budget</th><th className="num">Amount</th><th className="num">Counted</th><th>Buckets</th><th>Attachments</th>{canLines ? <th /> : null}</tr></thead>
              <tbody>
                {f.lines.map((l: any) => (
                  <tr key={l.allocation_id} className={l.excluded ? "fr-excluded" : ""}>
                    <td>{l.transaction_date}</td>
                    <td>{l.kind === "INCOME" ? "Income" : "Expense"}</td>
                    <td><Link to={`/register?account=${l.bank_account_id}&search=${encodeURIComponent(l.description || "")}`} title="Open in the Register">{l.bank_account}</Link></td>
                    <td>{l.entity || "—"}</td>
                    <td>{l.description || "—"}
                      {l.excluded ? <span className="badge grey" title={l.exclusion_reason}>Excluded: {l.exclusion_reason}</span> : null}
                      {l.classification ? <span className="badge blue" title={l.classification.note || ""}>{l.classification.label} {money(l.classification.amount)}</span> : null}
                    </td>
                    <td>{l.budget}</td>
                    <td className="num">{money(l.amount)}</td>
                    <td className="num">{l.excluded ? "—" : money(l.counted)}</td>
                    <td>{l.buckets.length ? l.buckets.map((b: any) => <span key={b.bucket_id} className="pill fr-bucket">{bucketName(b.bucket_id)} {money(b.amount)}{Number(b.less) ? <span className="muted"> ({money(b.charge)} less {money(b.less)} {b.less_description})</span> : null}{b.contributor_override ? <span className="muted"> · shown as “{b.contributor_override}”</span> : null}</span>) : <span className="muted">—</span>}
                      {l.over_assigned ? <span className="badge yellow">More than counted</span> : null}</td>
                    <td>{l.attachments.length ? l.attachments.map((a: any) => <a key={a.id} href={a.content_url} target="_blank" rel="noopener" className="att-link">{a.original_filename}</a>) : <span className="muted">—</span>}</td>
                    {canLines ? <td className="row-actions">{l.read_only ? <span className="muted">Closed</span> : <button className="small" aria-label={`Manage line ${l.description || l.transaction_date}`} onClick={() => setLineEdit(l)}>Manage</button>}</td> : null}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="total-row"><th colSpan={7}>Income (counted)</th><th className="num">{money(t.income)}</th><th colSpan={canLines ? 3 : 2} /></tr>
                <tr className="total-row"><th colSpan={7}>Expenses (counted)</th><th className="num">{money(t.expense)}</th><th colSpan={canLines ? 3 : 2} /></tr>
              </tfoot>
            </table>
          </div>
        ) : <p className="muted">No transactions yet.</p>}
      </section>

      <section className="card">
        <Attachments ownerType="fundraiser" ownerId={id} canUpload={canLines} canRemove={canLines} canReorder={canLines} title="Fundraiser documents"
          hint={<p className="hint">Documents about the fundraiser itself — flyers, permits, tally sheets.</p>} />
      </section>

      <section className="card">
        <h2>Transaction attachments</h2>
        <p className="hint">Documents attached to the fundraiser's transactions (read only here; manage them in the Register).</p>
        {attachments.length ? (
          <ul className="att-list">
            {attachments.map((a: any) => (
              <li key={a.id}><a href={a.content_url} target="_blank" rel="noopener">{a.original_filename}</a> <span className="muted">· {a.line.transaction_date} · {a.line.description || a.line.entity || ""} · {money(a.line.amount)}</span></li>
            ))}
          </ul>
        ) : <p className="muted">No attachments.</p>}
      </section>

      {cancelling ? <CancelDialog f={f} onClose={() => setCancelling(false)} onSaved={(x) => { setF(x); setCancelling(false); }} /> : null}
      {countSheet ? <CountSheetDialog f={f} onClose={() => setCountSheet(false)} /> : null}
      {lineEdit ? <LineDialog f={f} line={lineEdit} onClose={() => setLineEdit(null)} onSaved={(x) => { setF(x); setLineEdit(null); }} /> : null}
      {bucketEdit ? <BucketDialog f={f} bucket={bucketEdit} onClose={() => setBucketEdit(null)} onSaved={(x) => { setF(x); setBucketEdit(null); }} /> : null}
      {categoryEdit ? <CategoryDialog f={f} category={categoryEdit} onClose={() => setCategoryEdit(null)} onSaved={(x) => { setF(x); setCategoryEdit(null); }} /> : null}
      {reporting ? <ReportDialog f={f} onClose={() => setReporting(false)} /> : null}
      {nextYear ? <FundraiserForm prefill={nextYear} onClose={() => setNextYear(null)} onSaved={(x) => { setNextYear(null); navigate(`/fundraisers/${x.id}`); }} /> : null}
      {linking ? <SeriesLinkDialog f={f} onClose={() => setLinking(false)} onSaved={(x) => { setF(x); setLinking(false); }} /> : null}
      {ordering ? <OrderDialog f={f} onClose={() => setOrdering(false)} onSaved={(x) => { setF(x); setOrdering(false); }} /> : null}
      {editing ? <FundraiserForm current={f} onClose={() => setEditing(false)} onSaved={(x) => { setF(x); setEditing(false); }} /> : null}
      {confirmDelete ? (
        <Modal title="Delete fundraiser" onClose={() => setConfirmDelete(false)}>
          <p>Delete <b>{f.name}</b>? Its settings are removed (the transactions stay in the Register). To keep it for reporting, archive it instead.</p>
          <div className="actions">
            <button onClick={() => setConfirmDelete(false)}>Cancel</button>
            <button className="danger" onClick={() => { setConfirmDelete(false); act(async () => { await api.delete(`/api/fundraisers/${id}`); navigate("/fundraisers"); }); }}>Delete</button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ create / edit (Budget Manager)
function FundraiserForm({ current, prefill, onClose, onSaved }: { current?: any; prefill?: any; onClose: () => void; onSaved: (f: any) => void }) {
  const src = current || prefill;
  const [v, setV] = useState({
    name: src?.name || "", description: src?.description || "",
    start_date: src?.start_date || "", end_date: src?.end_date || "",
    filter_text: src?.filter_text || "", filter_regex: !!src?.filter_regex,
  });
  // 2.1.0 (#277): "Continues from (previous fundraiser)"
  const [cont, setCont] = useState<string>(src?.continues_from_id ? String(src.continues_from_id) : "");
  const [contOpts, setContOpts] = useState<any[]>([]);
  // chosen budgets: "<fiscal year id>:<INCOME|EXPENSE>" -> budget id
  const [chosen, setChosen] = useState<Record<string, number>>(() => Object.fromEntries((current?.budgets || []).map((b: any) => [`${b.fiscal_year.id}:${b.kind}`, b.id])));
  const frozen = (current?.budgets || []).filter((b: any) => b.fiscal_year.status === "CLOSED");
  const [options, setOptions] = useState<any[] | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const end = v.end_date || v.start_date;

  useEffect(() => {
    if (!v.start_date || end < v.start_date) { setOptions([]); return; }
    api.get(`/api/fundraisers/budget-options?start_date=${v.start_date}&end_date=${end}`).then(setOptions, setErr);
  }, [v.start_date, end]);
  useEffect(() => {
    if (!v.start_date) { setContOpts([]); return; }
    api.get(`/api/fundraisers/continue-options?start_date=${v.start_date}${current ? `&fundraiser_id=${current.id}` : ""}`).then(setContOpts, () => setContOpts([]));
  }, [v.start_date]); // eslint-disable-line react-hooks/exhaustive-deps
  // "Create next year's from this one": the continuing budgets, once next year's options are known
  const prefilled = useRef(false);
  useEffect(() => {
    if (!prefill || prefilled.current || !options?.length) return;
    prefilled.current = true;
    const next: Record<string, number> = {};
    for (const o of options) {
      for (const kind of ["INCOME", "EXPENSE"] as const) {
        const hit = (kind === "INCOME" ? o.income : o.expense).find((b: any) => (prefill.budget_ids || []).includes(b.id));
        if (hit) next[`${o.fiscal_year.id}:${kind}`] = hit.id;
      }
    }
    setChosen(next);
  }, [options]); // eslint-disable-line react-hooks/exhaustive-deps

  const frozenKeys = new Set(frozen.map((b: any) => `${b.fiscal_year.id}:${b.kind}`));
  const eligibleFy = new Set((options || []).map((o) => String(o.fiscal_year.id)));
  const ids = Object.entries(chosen).filter(([k]) => frozenKeys.has(k) || eligibleFy.has(k.split(":")[0])).map(([, id]) => id);
  const idsKey = ids.slice().sort().join(",");

  const seq = useRef(0);
  useEffect(() => {
    const n = ++seq.current;
    const h = setTimeout(() => {
      api.post("/api/fundraisers/preview", { budget_ids: ids, filter_text: v.filter_text || null, filter_regex: v.filter_regex })
        .then((p) => n === seq.current && setPreview(p), (x) => n === seq.current && setPreview({ error: (x as Error).message }));
    }, 250);
    return () => clearTimeout(h);
  }, [idsKey, v.filter_text, v.filter_regex]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k: string) => (e: any) => setV({ ...v, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const pick = (key: string, value: string) => {
    const next = { ...chosen };
    if (value) next[key] = Number(value);
    else delete next[key];
    setChosen(next);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body: any = { name: v.name, description: v.description || null, start_date: v.start_date, end_date: v.end_date || null,
                   budget_ids: ids, filter_text: v.filter_text || null, filter_regex: v.filter_regex,
                   continues_from_id: cont ? Number(cont) : null };
    if (!current && prefill?.copy_buckets_from_id) body.copy_buckets_from_id = prefill.copy_buckets_from_id;
    try {
      onSaved(current ? await api.put(`/api/fundraisers/${current.id}`, body) : await api.post("/api/fundraisers", body));
    } catch (x) { setErr(x); }
  };
  const optionWarnings = (opts: any[], id?: number) => (opts.find((o) => o.id === id)?.warnings || []);

  return (
    <Modal title={current ? "Edit fundraiser" : prefill ? "New fundraiser (next year)" : "New fundraiser"} onClose={onClose} wide>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Name"><input required maxLength={120} value={v.name} onChange={set("name")} /></Field>
        <Field label="Description"><textarea rows={2} maxLength={2000} value={v.description} onChange={set("description")} /></Field>
        <div className="row fields">
          <Field label="Event start date" hint="The day(s) the event takes place."><input type="date" required value={v.start_date} onChange={set("start_date")} /></Field>
          <Field label="Event end date" hint="Leave empty for a one-day event."><input type="date" min={v.start_date || undefined} value={v.end_date} onChange={set("end_date")} /></Field>
        </div>
        <fieldset className="fr-budgets">
          <legend>Budgets</legend>
          <p className="hint">Everything allocated to these budgets counts — preparation before the event and deposits after it included.
            Budgets can be chosen from a Fiscal Year that is set up and open when the event is inside it or within 3 months of its start or end
            (at most two Fiscal Years, one income and one expense budget each). You can save the fundraiser now and add budgets later, e.g. once next year's Fiscal Year exists.</p>
          {frozen.map((b: any) => (
            <p key={b.id} className="muted">{b.fiscal_year.display_name} (closed) — {b.kind === "INCOME" ? "Income" : "Expense"}: {b.label}</p>
          ))}
          {!v.start_date ? <p className="muted">Enter the event date first.</p> : options === null ? <Loading /> : !options.length ? (
            <p className="muted">No open Fiscal Year is within 3 months of the event yet — save the fundraiser now and select its budgets once the Fiscal Year is set up.</p>
          ) : options.map((o) => (
            <div key={o.fiscal_year.id} className="fr-fy">
              <h3>{o.fiscal_year.label}</h3>
              <div className="row fields">
                {(["INCOME", "EXPENSE"] as const).map((kind) => {
                  const key = `${o.fiscal_year.id}:${kind}`;
                  const opts = kind === "INCOME" ? o.income : o.expense;
                  return (
                    <Field key={kind} label={`${kind === "INCOME" ? "Income" : "Expense"} budget (${o.fiscal_year.display_name})`}>
                      <select value={chosen[key] ? String(chosen[key]) : ""} onChange={(e) => pick(key, e.target.value)}>
                        <option value="">— none —</option>
                        {opts.map((b: any) => <option key={b.id} value={b.id}>{b.level ? "   " : ""}{b.label}{b.status === "REJECTED" || b.status === "INACTIVE" ? ` (${b.status.toLowerCase()})` : ""}</option>)}
                      </select>
                      {optionWarnings(opts, chosen[key]).map((w: any) => <span key={w.code} className="field-warn" role="note">{w.message}</span>)}
                    </Field>
                  );
                })}
              </div>
            </div>
          ))}
        </fieldset>
        <Field label="Continues from (previous fundraiser)" hint="Links this fundraiser with the same event in an earlier year, for the Fiscal Year fundraising report. Leave empty for a new, unlinked fundraiser.">
          <select value={cont} onChange={(e) => setCont(e.target.value)}>
            <option value="">— none (new event) —</option>
            {contOpts.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.year}){o.series_name ? ` — ${o.series_name}` : ""}</option>)}
            {cont && !contOpts.some((o) => String(o.id) === cont) ? <option value={cont}>{src?.series_link?.continues_from?.name || prefill?.from_name || `Fundraiser ${cont}`}</option> : null}
          </select>
        </Field>
        {prefill ? <p className="hint">Copied from <b>{prefill.from_name}</b>: name, description, filter, the continuing budgets and the buckets{prefill.categories?.length ? " and categories" : ""} ({(prefill.buckets || []).join(", ") || "none"}), without amounts. Change anything before saving.</p> : null}
        <Field label="Description filter (optional)" hint="Only lines whose description contains this text are included (any upper/lower case).">
          <input maxLength={200} value={v.filter_text} onChange={set("filter_text")} placeholder="e.g. Gala" />
        </Field>
        <label className="check"><input type="checkbox" checked={v.filter_regex} onChange={set("filter_regex")} /> Advanced: treat the filter as a regular expression</label>
        {v.filter_text ? <div className="alert warn" role="note"><b>Filter in use:</b> every transaction line must include the filter text in its description to count towards this fundraiser. Lines entered without it are left out, which affects the validity of the figures.</div> : null}
        {preview ? (
          <p className="hint" role="status" data-testid="fr-preview">
            {preview.error ? preview.error : `${preview.matched_lines} of ${preview.total_lines} line${preview.total_lines === 1 ? "" : "s"} in the selected budgets will be included.`}
            {preview.unmatched_samples?.length ? ` Not matching, e.g.: ${preview.unmatched_samples.join("; ")}.` : ""}
            {preview.shared_with?.filter((s: any) => s.id !== current?.id).length ? ` Also used by: ${preview.shared_with.filter((s: any) => s.id !== current?.id).map((s: any) => s.name).join(", ")} — totals overlap unless filters separate them.` : ""}
          </p>
        ) : null}
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" type="submit">{current ? "Save" : "Create fundraiser"}</button>
        </div>
      </GuardedForm>
    </Modal>
  );
}

// ------------------------------------------------------------------ v1.6.1 CR-034: buckets and line management
function BucketDialog({ f, bucket, onClose, onSaved }: { f: any; bucket: any; onClose: () => void; onSaved: (f: any) => void }) {
  const [v, setV] = useState({ name: bucket.name || "", description: bucket.description || "", category_id: bucket.category_id ? String(bucket.category_id) : "" });
  const [err, setErr] = useState<unknown>(null);
  const locked = !!f.read_only; // closed year: only the category can change
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = { name: v.name, description: v.description || null, category_id: v.category_id ? Number(v.category_id) : null };
    try {
      onSaved(bucket.id ? await api.put(`/api/fundraisers/${f.id}/buckets/${bucket.id}`, body) : await api.post(`/api/fundraisers/${f.id}/buckets`, body));
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={bucket.id ? "Edit bucket" : "New bucket"} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Bucket name" hint="For example: Food sales, Raffle, Tickets."><input required maxLength={80} disabled={locked} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></Field>
        <Field label="Description (optional)"><input maxLength={500} disabled={locked} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} /></Field>
        <Field label="Category (optional)">
          <select value={v.category_id} onChange={(e) => setV({ ...v, category_id: e.target.value })}>
            <option value="">No category</option>
            {f.buckets.categories.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

// 2.1.0 (#277): change or remove "Continues from" - any Fiscal Year, closed ones included (reporting only)
function SeriesLinkDialog({ f, onClose, onSaved }: { f: any; onClose: () => void; onSaved: (f: any) => void }) {
  const [opts, setOpts] = useState<any[]>([]);
  const [cont, setCont] = useState<string>(f.continues_from_id ? String(f.continues_from_id) : "");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get(`/api/fundraisers/continue-options?start_date=${f.start_date}&fundraiser_id=${f.id}`).then(setOpts, setErr); }, [f.id]);
  const save = async () => {
    setErr(null);
    try { onSaved(await api.put(`/api/fundraisers/${f.id}/series-link`, { continues_from_id: cont ? Number(cont) : null })); } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Link with an earlier year" onClose={onClose}>
      <ErrorBox error={err} />
      <p className="hint">The link is used only by the Fiscal Year fundraising report, so it can be changed even when the Fiscal Year is closed.</p>
      <Field label="Continues from (previous fundraiser)">
        <select value={cont} onChange={(e) => setCont(e.target.value)}>
          <option value="">— none (not linked) —</option>
          {opts.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.year}){o.series_name ? ` — ${o.series_name}` : ""}</option>)}
          {cont && !opts.some((o) => String(o.id) === cont) && f.series_link.continues_from ? <option value={cont}>{f.series_link.continues_from.name}</option> : null}
        </select>
      </Field>
      <div className="actions"><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save link</button></div>
    </Modal>
  );
}

// 2.1.0 (#275): the stakeholder report - status, Mark results final and summary notes (Budget Managers)
function StakeholderReport({ f, manage, onChanged, onOpen }: { f: any; manage: boolean; onChanged: (f: any) => void; onOpen: () => void }) {
  const st = f.report_status;
  const [notes, setNotes] = useState<string>(f.summary_notes || "");
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { setNotes(f.summary_notes || ""); }, [f.summary_notes]);
  const run = async (fn: () => Promise<any>) => {
    setErr(null); setSaved(false);
    try { onChanged(await fn()); setSaved(true); } catch (x) { setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="fr-report-h">
      <div className="charts-head">
        <h2 id="fr-report-h">Stakeholder report</h2>
        <button className="small" onClick={onOpen}>Report…</button>
      </div>
      <p className="hint">A clean Financial &amp; Proceeds Statement for the committee and stakeholders — headline figures, breakdowns by category and bucket, key takeaways. It has no transaction numbers, accounts, budgets or attachments; the audit detail is under Reports → Fundraiser detail (audit).</p>
      <ErrorBox error={err} />
      <p data-testid="fr-report-status"><b>Report status:</b> {st.text}
        {st.marked_final ? " (marked final)" : st.final_because_closed ? " (every Fiscal Year is closed)" : ""}
        {manage && !st.final_because_closed ? (
          <button className="small fr-final-btn" onClick={() => run(() => api.put(`/api/fundraisers/${f.id}/results-final`, { final: !st.marked_final }))}>
            {st.marked_final ? "Undo final" : "Mark results final"}
          </button>
        ) : null}
      </p>
      {manage ? (
        <>
          <Field label="Summary notes (printed under the key takeaways)">
            <textarea rows={3} maxLength={10000} value={notes} onChange={(e) => { setNotes(e.target.value); setSaved(false); }} />
          </Field>
          <div className="actions left">
            <button disabled={notes === (f.summary_notes || "")} onClick={() => run(() => api.put(`/api/fundraisers/${f.id}/summary-notes`, { summary_notes: notes }))}>Save notes</button>
            {saved ? <span className="ok-text" role="status">Saved.</span> : null}
          </div>
        </>
      ) : f.summary_notes ? <><h3>Summary notes</h3><p className="pre-wrap">{f.summary_notes}</p></> : null}
    </section>
  );
}

function ReportDialog({ f, onClose }: { f: any; onClose: () => void }) {
  const [o, setO] = useState({ itemized: true, names: true, plain_lines: false });
  const hasBuckets = f.buckets.items.length > 0;
  const href = (format: string, download = false) => {
    const p = new URLSearchParams({ format, itemized: String(o.itemized), names: String(o.names), plain_lines: String(!hasBuckets && o.plain_lines) });
    if (download) p.set("download", "true");
    return `/api/fundraisers/${f.id}/summary-report?${p.toString()}`;
  };
  return (
    <Modal title="Fundraiser report" onClose={onClose}>
      <p>The Financial &amp; Proceeds Statement for <b>{f.name}</b> ({f.report_status.text}). <b>Presentation</b> is the same figures as a slide deck with charts (.pptx — opens in PowerPoint, Google Slides and Keynote).</p>
      {hasBuckets ? (
        <label className="check"><input type="checkbox" checked={o.itemized} onChange={(e) => setO({ ...o, itemized: e.target.checked })} /> Itemized revenue <span className="muted">(off: a summary-only report)</span></label>
      ) : (
        <label className="check"><input type="checkbox" checked={o.plain_lines} onChange={(e) => setO({ ...o, plain_lines: e.target.checked })} /> Plain line list <span className="muted">(this fundraiser has no buckets)</span></label>
      )}
      <label className="check"><input type="checkbox" checked={o.names} onChange={(e) => setO({ ...o, names: e.target.checked })} /> Show contributor names <span className="muted">(off: “Contributor 1, 2…”, for reports that go outside the organization)</span></label>
      <div className="actions">
        <button onClick={onClose}>Done</button>
        <a className="button" href={`/api/fundraisers/${f.id}/presentation?itemized=${o.itemized}&names=${o.names}`}>Presentation</a>
        <a className="button" href={href("docx")}>Report (Word)</a>
        <a className="button primary" href={href("pdf")} target="_blank" rel="noopener">Report (PDF)</a>
      </div>
    </Modal>
  );
}

// 2.1.0 (#278): the buckets table grouped by category (each with a subtotal), then the uncategorized buckets
function BucketTable({ f, canLines, canArrange, onEdit, onEditCategory, onDelete, onDeleteCategory }: any) {
  const by: Record<number, any> = Object.fromEntries(f.buckets.items.map((b: any) => [b.id, b]));
  const bucketRow = (b: any, indent: boolean) => (
    <tr key={`b${b.id}`}>
      <td className={indent ? "indent" : ""}>{b.name}{b.description ? <span className="muted"> — {b.description}</span> : null}</td>
      <td className="num">{money(b.income)}</td><td className="num">{money(b.expense)}</td>
      <td className={`num ${Number(b.net) < 0 ? "neg" : ""}`}>{money(b.net)}</td>
      <td className="row-actions">{canArrange ? <>
        <button className="small" aria-label={`Edit bucket ${b.name}`} onClick={() => onEdit(b)}>Edit</button>
        {canLines ? <RowMenu name={`bucket ${b.name}`} actions={[{ label: "Delete", danger: true, onClick: () => onDelete(b) }]} /> : null}
      </> : null}</td>
    </tr>
  );
  return (
    <table className="table compact fr-bucket-table" data-testid="fr-buckets">
      <thead><tr><th>Bucket</th><th className="num">Income</th><th className="num">Expenses</th><th className="num">Net</th><th /></tr></thead>
      <tbody>
        {f.buckets.categories.map((c: any) => (
          <Fragment key={`c${c.id}`}>
            <tr className="category-row">
              <th scope="rowgroup" colSpan={4}>{c.name}{c.description ? <span className="muted"> — {c.description}</span> : null}</th>
              <td className="row-actions">{canArrange ? <>
                <button className="small" aria-label={`Edit category ${c.name}`} onClick={() => onEditCategory(c)}>Edit</button>
                <RowMenu name={`category ${c.name}`} actions={[{ label: "Delete", danger: true, onClick: () => onDeleteCategory(c) }]} />
              </> : null}</td>
            </tr>
            {c.bucket_ids.map((bid: number) => bucketRow(by[bid], true))}
            {c.bucket_ids.length ? null : <tr><td className="indent muted" colSpan={5}>No buckets in this category yet — choose it when editing a bucket.</td></tr>}
            <tr className="subtotal-row"><td className="indent">{c.name} subtotal</td><td className="num">{money(c.income)}</td><td className="num">{money(c.expense)}</td><td className={`num ${Number(c.net) < 0 ? "neg" : ""}`}>{money(c.net)}</td><td /></tr>
          </Fragment>
        ))}
        {f.buckets.uncategorized_ids.map((bid: number) => bucketRow(by[bid], false))}
        <tr className="subtotal-row"><td>Unassigned</td><td className="num">{money(f.buckets.unassigned.income)}</td><td className="num">{money(f.buckets.unassigned.expense)}</td><td className="num">{money(f.buckets.unassigned.net)}</td><td /></tr>
      </tbody>
    </table>
  );
}

function CategoryDialog({ f, category, onClose, onSaved }: { f: any; category: any; onClose: () => void; onSaved: (f: any) => void }) {
  const [v, setV] = useState({ name: category.name || "", description: category.description || "" });
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = { name: v.name, description: v.description || null };
    try {
      onSaved(category.id ? await api.put(`/api/fundraisers/${f.id}/categories/${category.id}`, body) : await api.post(`/api/fundraisers/${f.id}/categories`, body));
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={category.id ? "Edit category" : "New category"} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Category name" hint="For example: Sponsorships, Registrations, Day-of event."><input required maxLength={80} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></Field>
        <Field label="Description (optional)"><input maxLength={500} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} /></Field>
        <p className="hint">Categories only group buckets on this page and in the reports; they never change a figure.</p>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

function OrderList({ title, items, setItems }: { title: string; items: any[]; setItems: (x: any[]) => void }) {
  const move = (i: number, d: number) => { const n = [...items]; [n[i], n[i + d]] = [n[i + d], n[i]]; setItems(n); };
  return (
    <fieldset className="fr-budgets">
      <legend>{title}</legend>
      <ol className="att-list att-order" aria-label={`Order of ${title.toLowerCase()}`}>
        {items.map((x, i) => (
          <li key={x.id}>
            <span className="att-name">{x.name}</span>
            <button type="button" className="small" aria-label={`Move ${x.name} up`} disabled={i === 0} onClick={() => move(i, -1)}>▲</button>
            <button type="button" className="small" aria-label={`Move ${x.name} down`} disabled={i === items.length - 1} onClick={() => move(i, 1)}>▼</button>
          </li>
        ))}
      </ol>
    </fieldset>
  );
}

function OrderDialog({ f, onClose, onSaved }: { f: any; onClose: () => void; onSaved: (f: any) => void }) {
  const [cats, setCats] = useState<any[]>(f.buckets.categories);
  const [buckets, setBuckets] = useState<any[]>(f.buckets.items);
  const [err, setErr] = useState<unknown>(null);
  const same = (a: any[], b: any[]) => a.map((x) => x.id).join() === b.map((x) => x.id).join();
  const save = async () => {
    setErr(null);
    try {
      let out = f;
      if (!same(cats, f.buckets.categories)) out = await api.put(`/api/fundraisers/${f.id}/categories/order`, { ids: cats.map((c) => c.id) });
      if (!same(buckets, f.buckets.items)) out = await api.put(`/api/fundraisers/${f.id}/buckets/order`, { ids: buckets.map((b) => b.id) });
      onSaved(out);
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Reorder categories and buckets" onClose={onClose}>
      <ErrorBox error={err} />
      <p className="hint">The order is used on this page and in the fundraiser reports. Buckets are listed under their category in this order.</p>
      {cats.length > 1 ? <OrderList title="Categories" items={cats} setItems={setCats} /> : null}
      {buckets.length > 1 ? <OrderList title="Buckets" items={buckets} setItems={setBuckets} /> : null}
      <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save order</button></div>
    </Modal>
  );
}

const toCents = (s: string) => Math.round(Number(s || 0) * 100);
const fromCents = (c: number) => (c / 100).toFixed(2);

function LineDialog({ f, line, onClose, onSaved }: { f: any; line: any; onClose: () => void; onSaved: (f: any) => void }) {
  const ctype = f.classification_types.find((c: any) => c.applies_to === line.kind);
  const [excluded, setExcluded] = useState<boolean>(line.excluded);
  const [reason, setReason] = useState<string>(line.exclusion_reason || "");
  const [cls, setCls] = useState<boolean>(!!line.classification);
  const [clsAmount, setClsAmount] = useState<string>(line.classification?.amount || "");
  const [clsNote, setClsNote] = useState<string>(line.classification?.note || "");
  const [amounts, setAmounts] = useState<Record<number, string>>(() => Object.fromEntries(line.buckets.map((b: any) => [b.bucket_id, b.amount])));
  // 2.1.0 (#278): Charge / Less per bucket (net = charge - less is what counts); keyed by bucket id
  type CL = { on: boolean; charge: string; less: string; desc: string };
  const [cl, setCl] = useState<Record<number, CL>>(() => Object.fromEntries(line.buckets.filter((b: any) => Number(b.less) > 0)
    .map((b: any) => [b.bucket_id, { on: true, charge: b.charge, less: b.less, desc: b.less_description || "" }])));
  // build 4-6 feedback: the contributor shown on the reports for this bucket's part (e.g. "Cash", or a known name)
  const [who, setWho] = useState<Record<number, { on: boolean; text: string }>>(() => Object.fromEntries(line.buckets
    .filter((b: any) => b.contributor_override).map((b: any) => [b.bucket_id, { on: true, text: b.contributor_override }])));
  const [err, setErr] = useState<unknown>(null);
  const total = toCents(line.amount);
  const counted = total - (cls ? toCents(clsAmount) : 0);
  const netOf = (bid: number) => (cl[bid]?.on ? toCents(cl[bid].charge) - toCents(cl[bid].less) : toCents(amounts[bid] || ""));
  const assigned = f.buckets.items.reduce((n: number, b: any) => n + Math.max(0, netOf(b.id)), 0);
  const remaining = counted - assigned;
  const bucketBody = () => f.buckets.items.flatMap((b: any) => {
    const c = cl[b.id];
    const o = who[b.id]?.on && who[b.id].text.trim() ? { contributor_override: who[b.id].text.trim() } : {};
    if (c?.on) return toCents(c.charge) > 0 ? [{ bucket_id: b.id, charge: fromCents(toCents(c.charge)), less: fromCents(toCents(c.less)), less_description: c.desc || null, ...o }] : [];
    const a = amounts[b.id];
    return toCents(a) > 0 ? [{ bucket_id: b.id, amount: fromCents(toCents(a)), ...o }] : [];
  });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = excluded
      ? { excluded: true, exclusion_reason: reason }
      : {
          excluded: false,
          classification: cls && ctype ? { kind: ctype.kind, amount: clsAmount, note: clsNote || null } : null,
          buckets: bucketBody(),
        };
    try { onSaved(await api.put(`/api/fundraisers/${f.id}/lines/${line.allocation_id}`, body)); } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Manage transaction line" onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <p><b>{line.transaction_date}</b> · {line.kind === "INCOME" ? "Income" : "Expense"} · {line.description || line.entity || "—"} · <b>{money(line.amount)}</b></p>
        <ErrorBox error={err} />
        <label className="check"><input type="checkbox" checked={excluded} onChange={(e) => setExcluded(e.target.checked)} /> Exclude this line from the fundraiser</label>
        {excluded ? (
          <Field label="Reason for excluding" hint="The line stays in the Register and its budget; it just does not count for this fundraiser."><input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        ) : (
          <>
            {ctype ? (
              <fieldset className="fr-budgets">
                <legend>Special classification</legend>
                <label className="check"><input type="checkbox" checked={cls} onChange={(e) => setCls(e.target.checked)} /> {ctype.label}</label>
                <p className="hint">{line.kind === "EXPENSE"
                  ? "Cash taken out of the bank for the cash box. It is not an expense of the fundraiser."
                  : "Cash float coming back inside this deposit. It is not income of the fundraiser."}</p>
                {cls ? (
                  <div className="row fields">
                    <Field label="Cash float amount"><input required inputMode="decimal" value={clsAmount} onChange={(e) => setClsAmount(e.target.value)} placeholder={line.amount} /></Field>
                    <Field label="Note (optional)"><input maxLength={500} value={clsNote} onChange={(e) => setClsNote(e.target.value)} /></Field>
                  </div>
                ) : null}
              </fieldset>
            ) : null}
            <fieldset className="fr-budgets">
              <legend>Buckets</legend>
              {f.buckets.items.length ? (
                <>
                  {f.buckets.items.map((b: any) => {
                    const c = cl[b.id];
                    const mine = Math.max(0, netOf(b.id));
                    const setC = (x: Partial<CL>) => setCl({ ...cl, [b.id]: { on: true, charge: c?.charge ?? (amounts[b.id] || ""), less: c?.less ?? "", desc: c?.desc ?? "", ...x } });
                    return (
                      <div key={b.id} className={`fr-bucket-row${c?.on ? " with-credit" : ""}`}>
                        {c?.on ? (
                          <div className="fr-credit">
                            <span className="field-label">{b.name}</span>
                            <div className="row fields">
                              <Field label="Charge"><input inputMode="decimal" aria-label={`Charge for ${b.name}`} value={c.charge} placeholder="0.00" onChange={(e) => setC({ charge: e.target.value })} /></Field>
                              <Field label="Less"><input inputMode="decimal" aria-label={`Less for ${b.name}`} value={c.less} placeholder="0.00" onChange={(e) => setC({ less: e.target.value })} /></Field>
                              <Field label="Less description"><input maxLength={200} aria-label={`Less description for ${b.name}`} required={toCents(c.less) > 0} value={c.desc} placeholder="e.g. Pre-paid team credit" onChange={(e) => setC({ desc: e.target.value })} /></Field>
                            </div>
                            <p className="hint" role="status">Net {money(fromCents(toCents(c.charge) - toCents(c.less)))} counts for this line.{toCents(c.less) > toCents(c.charge) ? " The Less amount can't be more than the Charge." : ""}</p>
                          </div>
                        ) : (
                          <label className="field-inner"><span className="field-label">{b.name}</span>
                            <input inputMode="decimal" aria-label={`Amount for ${b.name}`} value={amounts[b.id] || ""} placeholder="0.00"
                                   onChange={(e) => setAmounts({ ...amounts, [b.id]: e.target.value })} /></label>
                        )}
                        <div className="fr-bucket-buttons">
                          <button type="button" className="small" disabled={remaining + mine <= 0}
                                  onClick={() => c?.on ? setC({ charge: fromCents(remaining + mine + toCents(c.less)) }) : setAmounts({ ...amounts, [b.id]: fromCents(remaining + mine) })}>All remaining</button>
                          <label className="check small"><input type="checkbox" checked={!!c?.on} aria-label={`Charge less a credit for ${b.name}`}
                            onChange={(e) => e.target.checked ? setC({}) : (setCl({ ...cl, [b.id]: { ...(c as CL), on: false } }), setAmounts({ ...amounts, [b.id]: fromCents(mine) }))} /> Charge less a credit</label>
                          <label className="check small"><input type="checkbox" checked={!!who[b.id]?.on} aria-label={`Show a different contributor for ${b.name}`}
                            onChange={(e) => setWho({ ...who, [b.id]: { on: e.target.checked, text: who[b.id]?.text || "" } })} /> Different contributor on reports</label>
                        </div>
                        {who[b.id]?.on ? (
                          <div className="fr-who">
                            <Field label="Shown on the reports as" hint={`Instead of ${line.entity || "the line's Entity"} — e.g. "Cash" for lump cash collected, or the name people know the contributor by.`}>
                              <input maxLength={120} aria-label={`Contributor shown for ${b.name}`} value={who[b.id].text} placeholder="e.g. Cash"
                                     onChange={(e) => setWho({ ...who, [b.id]: { on: true, text: e.target.value } })} />
                            </Field>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                  <p className={`hint ${remaining < 0 ? "neg" : ""}`} role="status" data-testid="fr-line-remaining">
                    Counts for the fundraiser: {money(fromCents(counted))} · assigned {money(fromCents(assigned))} · {remaining < 0 ? `over by ${money(fromCents(-remaining))}` : `unassigned ${money(fromCents(remaining))}`}
                  </p>
                </>
              ) : <p className="muted">No buckets yet — create one in the Buckets section first.</p>}
            </fieldset>
          </>
        )}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit" disabled={!excluded && (remaining < 0 || Object.values(cl).some((c) => c.on && toCents(c.less) > toCents(c.charge)))}>Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

// ------------------------------------------------------------------ v1.6.4 CR-037: cancel; CR-038: cash count sheet
function CancelDialog({ f, onClose, onSaved }: { f: any; onClose: () => void; onSaved: (f: any) => void }) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { onSaved(await api.post(`/api/fundraisers/${f.id}/cancel`, { reason })); } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Mark fundraiser as cancelled" onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <p>Use this when <b>{f.name}</b> did not take place as planned. Expenses and deposits already made stay listed and counted; the fundraiser, its report and the Audit / Close reports show that it was cancelled. You can reinstate it later.</p>
        <ErrorBox error={err} />
        <Field label="Reason"><input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Back</button><button className="primary" type="submit">Mark as cancelled</button></div>
      </GuardedForm>
    </Modal>
  );
}

function CountSheetDialog({ f, onClose }: { f: any; onClose: () => void }) {
  const [people, setPeople] = useState<any[]>([]);
  const [signers, setSigners] = useState<{ entity_id: string; title: string }[]>([0, 1].map(() => ({ entity_id: "", title: "" })));
  const [extra, setExtra] = useState(true);   // 1.6.7: page 2 with more check lines (print on the back)
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    api.get("/api/entities").then((es: any[]) => setPeople(es.filter((e) => e.entity_type === "INDIVIDUAL" && !e.is_system && e.active !== false)), setErr);
  }, []);
  const chosen = signers.filter((x) => x.entity_id);
  const ids = chosen.map((x) => x.entity_id);
  const blank = signers.length - chosen.length;
  const maxBlank = chosen.length ? 2 : 3;   // 1.6.7: room to print names by hand - 3 blank rows, or 2 next to chosen signers
  const problem = new Set(ids).size !== ids.length ? "Each signer can be listed only once."
    : signers.some((x) => !x.entity_id && x.title.trim()) ? "A title was entered without choosing a signer."
    : blank > maxBlank ? `At most ${maxBlank} rows can be left empty${chosen.length ? " next to chosen signers" : ""}. Choose a signer for the others or remove them.` : null;
  const p = new URLSearchParams();
  chosen.forEach((x) => { p.append("signer_id", x.entity_id); p.append("signer_title", x.title.trim()); });
  if (!extra) p.append("extra_checks", "false");
  p.append("blank_lines", String(blank));   // 1.6.7: a row left empty prints a blank row
  const href = `/api/fundraisers/${f.id}/count-sheet?${p.toString()}`;
  const upd = (i: number, patch: object) => setSigners(signers.map((y, j) => (j === i ? { ...y, ...patch } : y)));
  return (
    <Modal title="Cash count sheet" onClose={onClose}>
      <p>A blank sheet to print: bills and coins, checks, totals, notes and signature lines. Fill it in by hand at the count, have everyone sign, then scan it and add it under <b>Fundraiser documents</b>.</p>
      <ErrorBox error={err} />
      <h3>Signature lines (1 to 5)</h3>
      {signers.map((x, i) => (
        <div key={i} className="sig-signer row">
          <div className="grow"><EntityPicker label={`Signer ${i + 1}`} entities={people} value={x.entity_id} onChange={(v) => upd(i, { entity_id: v, title: positionTitle(people, x, v) })} /></div>
          <label className="field-inner"><span className="field-label">Title (optional)</span><input aria-label={`Signer ${i + 1} title`} maxLength={60} value={x.title} placeholder="e.g. Treasurer" onChange={(e) => upd(i, { title: e.target.value })} /></label>
          {signers.length > 1 ? <button type="button" className="small" aria-label={`Remove signer ${i + 1}`} onClick={() => setSigners(signers.filter((_, j) => j !== i))}>Remove</button> : null}
        </div>
      ))}
      {signers.length < 5 && blank < maxBlank ? <button type="button" className="small" onClick={() => setSigners([...signers, { entity_id: "", title: "" }])}>+ Add signature line</button> : null}
      <p className="hint">Choose a signer (an individual Entity) to print the name under the signature line, or leave the row empty for blank <b>Signature</b>, <b>Printed</b> name and <b>Date</b> lines to fill in by hand. A signer's saved position is filled in as the title. Up to 5 rows; at most 3 may be empty (2 when signers are chosen) so there is room to write.</p>
      <h3>Checks</h3>
      <label className="check"><input type="checkbox" checked={extra} onChange={(e) => setExtra(e.target.checked)} /> Add page 2 for more checks</label>
      <p className="hint">Page 1 has 13 check lines. Page 2 has 30 more and their own total — print it on the back (two-sided printing) or as a second sheet, or print page 1 only when it is not needed.</p>
      {problem ? <div className="alert error" role="alert">{problem}</div> : null}
      <div className="actions">
        <button type="button" onClick={onClose}>Close</button>
        {problem ? null : <a className="button primary" href={href} target="_blank" rel="noopener">Open sheet (PDF)</a>}
      </div>
    </Modal>
  );
}
