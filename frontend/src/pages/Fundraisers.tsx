// v1.6.0 CR-033: Fundraiser module - list per Fiscal Year (+ upcoming), details, create/edit (Budget Manager).
import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
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
  }, [fy, archived]);

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
        {can("fundraiser.manage") ? <button className="primary" onClick={() => setCreating(true)}>New fundraiser</button> : null}
      </div>
      <ErrorBox error={err} />
      {!rows ? <Loading /> : !rows.length ? (
        <p className="muted">{fy === UPCOMING ? "No fundraisers for events beyond the Fiscal Years set up so far." : "No fundraisers in this Fiscal Year."}</p>
      ) : (
        <table className="table" data-testid="fundraiser-list">
          <thead><tr><th>Fundraiser</th><th>Event</th><th>Status</th><th>Fiscal Years</th><th className="num">Income</th><th className="num">Expenses</th><th className="num">Net</th></tr></thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.id}>
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
    </div>
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
  const [cancelling, setCancelling] = useState(false); // v1.6.4 CR-037
  const [countSheet, setCountSheet] = useState(false); // v1.6.4 CR-038
  const load = () => api.get(`/api/fundraisers/${id}`).then(setF, setErr);
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!f) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const manage = can("fundraiser.manage");
  const canLines = can("fundraiser.lines") && !f.read_only; // Budget Manager / Register User
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
        <a className="button" href={`/api/fundraisers/${id}/report`} target="_blank" rel="noopener">Report (PDF)</a>
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
            <button className="danger" onClick={() => setConfirmDelete(true)}>Delete…</button>
          </div>
        ) : null}
      </div>
      <dl className="dl">
        <dt>Event</dt><dd data-testid="fr-event">{eventDates(f)}</dd>
        <dt>Fiscal Years</dt><dd>{f.fiscal_years.length ? f.fiscal_years.map((y: any) => y.display_name).join(" – ") : "—"}</dd>
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

      <section className="card" aria-labelledby="fr-buckets-h">
        <div className="charts-head">
          <h2 id="fr-buckets-h">Buckets</h2>
          {canLines ? <button className="small" onClick={() => setBucketEdit({})}>New bucket</button> : null}
        </div>
        <p className="hint">Buckets break the fundraiser down by offering (for example food sales or a raffle). Assign amounts of transaction lines to them with <b>Manage</b> in the transaction list.</p>
        {f.buckets.items.length ? (
          <table className="table compact" data-testid="fr-buckets">
            <thead><tr><th>Bucket</th><th className="num">Income</th><th className="num">Expenses</th><th className="num">Net</th><th /></tr></thead>
            <tbody>
              {f.buckets.items.map((b: any) => (
                <tr key={b.id}>
                  <td>{b.name}{b.description ? <span className="muted"> — {b.description}</span> : null}</td>
                  <td className="num">{money(b.income)}</td><td className="num">{money(b.expense)}</td>
                  <td className={`num ${Number(b.net) < 0 ? "neg" : ""}`}>{money(b.net)}</td>
                  <td className="row-actions">{canLines ? <>
                    <button className="small" aria-label={`Edit bucket ${b.name}`} onClick={() => setBucketEdit(b)}>Edit</button>
                    <RowMenu name={`bucket ${b.name}`} actions={[
                      { label: "Delete", danger: true, onClick: () => window.confirm(`Delete the bucket “${b.name}”? Its lines become unassigned.`) && act(async () => setF(await api.delete(`/api/fundraisers/${id}/buckets/${b.id}`))) },
                    ]} />
                  </> : null}</td>
                </tr>
              ))}
              <tr className="subtotal-row"><td>Unassigned</td><td className="num">{money(f.buckets.unassigned.income)}</td><td className="num">{money(f.buckets.unassigned.expense)}</td><td className="num">{money(f.buckets.unassigned.net)}</td><td /></tr>
            </tbody>
          </table>
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
                    <td>{l.buckets.length ? l.buckets.map((b: any) => <span key={b.bucket_id} className="pill fr-bucket">{bucketName(b.bucket_id)} {money(b.amount)}</span>) : <span className="muted">—</span>}
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
        <Attachments ownerType="fundraiser" ownerId={id} canUpload={canLines} canRemove={canLines} title="Fundraiser documents"
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
function FundraiserForm({ current, onClose, onSaved }: { current?: any; onClose: () => void; onSaved: (f: any) => void }) {
  const [v, setV] = useState({
    name: current?.name || "", description: current?.description || "",
    start_date: current?.start_date || "", end_date: current?.end_date || "",
    filter_text: current?.filter_text || "", filter_regex: !!current?.filter_regex,
  });
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
    const body = { name: v.name, description: v.description || null, start_date: v.start_date, end_date: v.end_date || null,
                   budget_ids: ids, filter_text: v.filter_text || null, filter_regex: v.filter_regex };
    try {
      onSaved(current ? await api.put(`/api/fundraisers/${current.id}`, body) : await api.post("/api/fundraisers", body));
    } catch (x) { setErr(x); }
  };
  const optionWarnings = (opts: any[], id?: number) => (opts.find((o) => o.id === id)?.warnings || []);

  return (
    <Modal title={current ? "Edit fundraiser" : "New fundraiser"} onClose={onClose} wide>
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
  const [v, setV] = useState({ name: bucket.name || "", description: bucket.description || "" });
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = { name: v.name, description: v.description || null };
    try {
      onSaved(bucket.id ? await api.put(`/api/fundraisers/${f.id}/buckets/${bucket.id}`, body) : await api.post(`/api/fundraisers/${f.id}/buckets`, body));
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={bucket.id ? "Edit bucket" : "New bucket"} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Bucket name" hint="For example: Food sales, Raffle, Tickets."><input required maxLength={80} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></Field>
        <Field label="Description (optional)"><input maxLength={500} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
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
  const [err, setErr] = useState<unknown>(null);
  const total = toCents(line.amount);
  const counted = total - (cls ? toCents(clsAmount) : 0);
  const assigned = Object.values(amounts).reduce((n, a) => n + toCents(a), 0);
  const remaining = counted - assigned;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = excluded
      ? { excluded: true, exclusion_reason: reason }
      : {
          excluded: false,
          classification: cls && ctype ? { kind: ctype.kind, amount: clsAmount, note: clsNote || null } : null,
          buckets: Object.entries(amounts).filter(([, a]) => toCents(a) > 0).map(([bid, a]) => ({ bucket_id: Number(bid), amount: fromCents(toCents(a)) })),
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
                  {f.buckets.items.map((b: any) => (
                    <div key={b.id} className="fr-bucket-row">
                      <label className="field-inner"><span className="field-label">{b.name}</span>
                        <input inputMode="decimal" aria-label={`Amount for ${b.name}`} value={amounts[b.id] || ""} placeholder="0.00"
                               onChange={(e) => setAmounts({ ...amounts, [b.id]: e.target.value })} /></label>
                      <button type="button" className="small" disabled={remaining + toCents(amounts[b.id] || "") <= 0}
                              onClick={() => setAmounts({ ...amounts, [b.id]: fromCents(remaining + toCents(amounts[b.id] || "")) })}>All remaining</button>
                    </div>
                  ))}
                  <p className={`hint ${remaining < 0 ? "neg" : ""}`} role="status" data-testid="fr-line-remaining">
                    Counts for the fundraiser: {money(fromCents(counted))} · assigned {money(fromCents(assigned))} · {remaining < 0 ? `over by ${money(fromCents(-remaining))}` : `unassigned ${money(fromCents(remaining))}`}
                  </p>
                </>
              ) : <p className="muted">No buckets yet — create one in the Buckets section first.</p>}
            </fieldset>
          </>
        )}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit" disabled={!excluded && remaining < 0}>Save</button></div>
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
