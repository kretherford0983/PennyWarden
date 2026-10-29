import { useEffect, useState, type FormEvent } from "react";
import { api, money, qs } from "../api";
import { ErrorBox, Field, GuardedForm, Loading, Modal } from "../components";

/** 2.2.0 (#381): budgets from before PennyWarden ("former budgets") - one line of the old spreadsheets each, with its
 * years (Entered). A PennyWarden budget reaches them only through an explicit link, never by code. Budget Managers
 * manage them; every financial role and Auditors read them. */

const TYPE: Record<string, string> = { INCOME: "Income", EXPENSE: "Expense" };

export function FormerBudgetsDialog({ fys, manage, onClose, onChanged }: { fys: any[]; manage: boolean; onClose: () => void; onChanged: () => void }) {
  const [list, setList] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [showRetired, setShowRetired] = useState(false);
  const load = () => api.get("/api/budgets/former").then(setList, setErr);
  useEffect(() => { load(); }, []);
  const changed = () => { load(); onChanged(); };
  const shown = (list || []).filter((f) => showRetired || !f.retired);
  const retiredCount = (list || []).filter((f) => f.retired).length;
  return (
    <Modal title="Budgets from before PennyWarden" onClose={onClose} wide>
      <p>
        Budgets as they were in your earlier spreadsheets, with their budgeted and actual figures by year. A budget in
        PennyWarden shows those years once it <i>continues</i> one of them (its History, the Budget Review and the
        Planning Sheet). Links never go by code, so a code that was reused for a different budget stays separate.
      </p>
      <ErrorBox error={err} />
      {manage ? <div className="actions left"><button type="button" className="primary" onClick={() => setCreating(true)}>New budget from before PennyWarden</button></div> : null}
      {!list ? (err ? null : <Loading />) : !shown.length ? (
        <p className="muted">None yet. Add one here, use <i>Add an earlier year</i> on a budget's History, or import a CSV file (<i>Import earlier years…</i>).</p>
      ) : (
        <div className="table-wrap">
          <table className="table" aria-label="Budgets from before PennyWarden">
            <thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Years</th><th className="num">Budgeted</th><th className="num">Actual</th><th>Continued by</th><th /></tr></thead>
            <tbody>
              {shown.map((f) => (
                <tr key={f.id} className={f.retired ? "muted" : ""}>
                  <td><span className="code">{f.code}</span></td>
                  <td>{f.name}{f.retired ? <span className="badge grey" style={{ marginLeft: 6 }}>Retired</span> : null}</td>
                  <td>{TYPE[f.budget_type]}</td>
                  <td>{f.years ? <>{f.years} ({f.first_year_entered}{f.years > 1 ? `–${f.last_year_entered}` : ""})</> : <span className="muted">none</span>}</td>
                  <td className="num">{money(f.budgeted_total)}</td><td className="num">{money(f.actual_total)}</td>
                  <td>{f.continued_by ? f.continued_by.label : <span className="muted">Not continued</span>}</td>
                  <td><button type="button" className="small" aria-label={`Open ${f.label}`} onClick={() => setOpen(f.id)}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {retiredCount ? <label className="check"><input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} /> Show retired ({retiredCount})</label> : null}
      {creating ? <FormerForm onClose={() => setCreating(false)} onSaved={(f) => { setCreating(false); changed(); setOpen(f.id); }} /> : null}
      {open !== null ? <FormerDetail id={open} fys={fys} manage={manage} onClose={() => setOpen(null)} onChanged={changed} /> : null}
      <div className="actions"><button type="button" onClick={onClose}>Close</button></div>
    </Modal>
  );
}

/** Create, or edit code / name / type / note (type only while no budget continues it). */
export function FormerForm({ former, onClose, onSaved }: { former?: any; onClose: () => void; onSaved: (f: any) => void }) {
  const [f, setF] = useState({ code: former?.default_code || "", name: former?.default_name || "", budget_type: former?.budget_type || "EXPENSE", note: former?.note || "", reason: "" });
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = former
        ? await api.patch(`/api/budgets/former/${former.id}`, { code: f.code, name: f.name, budget_type: f.budget_type, note: f.note || null, reason: f.reason || null })
        : await api.post("/api/budgets/former", { code: f.code, name: f.name, budget_type: f.budget_type, note: f.note || null });
      onSaved(r);
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={former ? `Edit ${former.label}` : "New budget from before PennyWarden"} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <div className="row fields">
          <Field label="Code" hint="As it was in the old spreadsheets."><input required maxLength={20} value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
          <Field label="Name"><input required maxLength={120} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        </div>
        <Field label="Type" hint={former?.continued_by ? "Unlink it first to change the type." : undefined}>
          <select value={f.budget_type} disabled={!!former?.continued_by} onChange={(e) => setF({ ...f, budget_type: e.target.value })}>
            <option value="INCOME">Income</option><option value="EXPENSE">Expense</option>
          </select>
        </Field>
        <Field label="Note (optional)"><input maxLength={500} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
        {former ? <Field label="Reason (optional)"><input maxLength={500} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field> : null}
        {former ? <p className="hint">A year that was called differently keeps its own code and name (Correct the year).</p> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">{former ? "Save" : "Create"}</button></div>
      </GuardedForm>
    </Modal>
  );
}

function FormerDetail({ id, fys, manage, onClose, onChanged }: { id: number; fys: any[]; manage: boolean; onClose: () => void; onChanged: () => void }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [edit, setEdit] = useState<any>(null); // {mode: add|correct|retire, e} | {mode: "edit"} | {mode: "link"} | {mode: "retire-former"}
  const load = () => api.get(`/api/budgets/former/${id}`).then(setD, setErr);
  useEffect(() => { load(); }, [id]);
  const done = () => { setEdit(null); load(); onChanged(); };
  const unlink = async () => {
    if (!d?.continued_by) return;
    try { await api.put(`/api/budgets/${d.continued_by.id}/former-link`, { former_budget_id: null }); done(); } catch (x) { setErr(x); }
  };
  const live = d && !d.retired;
  const shown = (d?.entries || []).filter((x: any) => !x.retired);
  const retired = (d?.entries || []).filter((x: any) => x.retired);
  return (
    <Modal title={d ? `${d.label} (before PennyWarden)` : "Budget from before PennyWarden"} onClose={onClose} wide>
      <ErrorBox error={err} />
      {!d ? (err ? null : <Loading />) : (
        <>
          <p>
            {TYPE[d.budget_type]}{d.note ? <> · <span className="muted">{d.note}</span></> : null}
            {d.retired ? <> · <b>Retired</b>: {d.retire_reason}</> : null}
          </p>
          <p data-testid="former-continued-by">
            {d.continued_by ? <>Continued by <b>{d.continued_by.label}</b>.</> : <span className="muted">No budget in PennyWarden continues it.</span>}
            {manage && live ? <>
              {" "}<button type="button" className="small" onClick={() => setEdit({ mode: "link" })}>{d.continued_by ? "Change…" : "Link to a budget…"}</button>
              {d.continued_by ? <> <button type="button" className="small" onClick={unlink}>Unlink</button></> : null}
            </> : null}
          </p>
          <div className="table-wrap">
            <table className="table" aria-label="Years before PennyWarden">
              <thead><tr><th>Fiscal Year</th><th>Code and name that year</th><th className="num">Budgeted</th><th className="num">Actual</th><th>Note</th>{manage && live ? <th /> : null}</tr></thead>
              <tbody>
                {!shown.length ? <tr><td colSpan={6} className="muted">No years entered yet.</td></tr> : null}
                {shown.map((x: any) => (
                  <tr key={x.id}>
                    <td>{x.fiscal_year_label}{x.estimated ? <span title="Estimated" data-testid="estimated-mark">*</span> : null} <span className="badge grey">Entered</span>{!x.counted ? <div className="muted small">Not counted: a Fiscal Year in PennyWarden covers this year.</div> : null}</td>
                    <td><span className="code">{x.code_shown}</span> {x.name_shown}</td>
                    <td className="num">{money(x.budgeted)}</td><td className="num">{money(x.actual)}</td>
                    <td className="muted">{x.note}</td>
                    {manage && live ? <td><span className="row-buttons">
                      <button type="button" className="small" aria-label={`Correct ${x.fiscal_year_label}`} onClick={() => setEdit({ mode: "correct", e: x })}>Correct</button>
                      <button type="button" className="small" aria-label={`Retire ${x.fiscal_year_label}`} onClick={() => setEdit({ mode: "retire", e: x })}>Retire</button>
                    </span></td> : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {retired.length ? (
            <details className="retired-entries">
              <summary>Retired entries ({retired.length})</summary>
              <ul>{retired.map((x: any) => <li key={x.id}>{x.fiscal_year_label}: {money(x.budgeted)} budgeted, {money(x.actual)} actual — retired: {x.retire_reason}</li>)}</ul>
            </details>
          ) : null}
          {manage && live ? (
            <div className="actions left">
              <button type="button" onClick={() => setEdit({ mode: "add" })}>Add a year</button>
              <button type="button" onClick={() => setEdit({ mode: "edit" })}>Edit…</button>
              <button type="button" className="danger" onClick={() => setEdit({ mode: "retire-former" })}>Retire…</button>
            </div>
          ) : null}
        </>
      )}
      {edit && ["add", "correct", "retire"].includes(edit.mode) ? (
        <YearForm title={edit.mode === "add" ? `Add a year to ${d.label}` : undefined} addUrl={`/api/budgets/former/${id}/entries`} edit={edit} defaults={{ code: d.default_code, name: d.default_name }} onClose={() => setEdit(null)} onSaved={done} />
      ) : null}
      {edit?.mode === "edit" ? <FormerForm former={d} onClose={() => setEdit(null)} onSaved={done} /> : null}
      {edit?.mode === "link" ? <LinkForm former={d} fys={fys} onClose={() => setEdit(null)} onSaved={done} /> : null}
      {edit?.mode === "retire-former" ? <RetireFormer former={d} onClose={() => setEdit(null)} onSaved={done} /> : null}
      <div className="actions"><button type="button" onClick={onClose}>Close</button></div>
    </Modal>
  );
}

/** Choose the PennyWarden budget that continues a former budget: a Fiscal Year, then one of its budgets (the earliest
 * of each line; -00 Other of a parent with sub-budgets too). Any level, same type. */
function LinkForm({ former, fys, onClose, onSaved }: any) {
  const [fyId, setFyId] = useState<number>(fys.length ? fys[0].id : 0);
  const [opts, setOpts] = useState<any[] | null>(null);
  const [pick, setPick] = useState("");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (!fyId) return;
    setOpts(null); setPick("");
    api.get(`/api/budgets/former/${former.id}/budget-options${qs({ fiscal_year_id: fyId })}`).then(setOpts, setErr);
  }, [fyId]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      if (former.continued_by && String(former.continued_by.id) !== pick) await api.put(`/api/budgets/${former.continued_by.id}/former-link`, { former_budget_id: null });
      await api.put(`/api/budgets/${pick}/former-link`, { former_budget_id: former.id });
      onSaved();
    } catch (x) { setErr(x); }
  };
  const chosen = (opts || []).find((o) => String(o.id) === pick);
  return (
    <Modal title={`Link ${former.label} to a budget`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <p className="hint">Usually the budget in your first Fiscal Year in PennyWarden. Later years of the same budget follow through their own links.</p>
        <Field label="Fiscal Year">
          <select aria-label="Link Fiscal Year" value={fyId} onChange={(e) => setFyId(Number(e.target.value))}>
            {fys.map((f: any) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </Field>
        <Field label="Budget" hint={`${TYPE[former.budget_type]} budgets that start their line in this Fiscal Year.`}>
          <select aria-label="Link budget" required value={pick} onChange={(e) => setPick(e.target.value)} disabled={opts === null}>
            <option value="">— Choose —</option>
            {(opts || []).map((o) => <option key={o.id} value={o.id}>{o.code} {o.name}{o.continues && o.continues.id !== former.id ? ` (continues ${o.continues.label})` : ""}</option>)}
          </select>
        </Field>
        {chosen?.continues && chosen.continues.id !== former.id ? <div className="alert warn" role="alert">{chosen.code} {chosen.name} continues {chosen.continues.label} now; that link is replaced.</div> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit" disabled={!pick}>Link</button></div>
      </GuardedForm>
    </Modal>
  );
}

function RetireFormer({ former, onClose, onSaved }: any) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post(`/api/budgets/former/${former.id}/retire`, { reason }); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Retire ${former.label}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <p>Its years stop counting{former.continued_by ? <> and {former.continued_by.label} no longer continues it</> : null}. It is kept, with your reason, and can't be deleted.</p>
        <Field label="Reason (required)"><textarea required value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary danger" type="submit" disabled={!reason.trim()}>Retire</button></div>
      </GuardedForm>
    </Modal>
  );
}

/** 2.2.0 (#284, #381): add, correct (reason required) or retire (reason required) an entered year; optionally the code
 * and name the budget had that year. */
export function YearForm({ title, addUrl, edit, defaults, onClose, onSaved }: {
  title?: string; addUrl: string; edit: any; defaults?: { code?: string; name?: string }; onClose: () => void; onSaved: () => void;
}) {
  const e = edit.e || {};
  const [f, setF] = useState({ fiscal_year_label: e.fiscal_year_label || "", budgeted: e.budgeted || "", actual: e.actual || "", note: e.note || "",
                               code: e.code || "", name: e.name || "", reason: "", estimated: !!e.estimated });
  const [err, setErr] = useState<unknown>(null);
  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setErr(null);
    try {
      if (edit.mode === "add") await api.post(addUrl, { fiscal_year_label: f.fiscal_year_label, budgeted: f.budgeted, actual: f.actual, note: f.note || null, code: f.code || null, name: f.name || null, estimated: f.estimated });
      else if (edit.mode === "correct") await api.patch(`/api/budgets/history-entries/${e.id}`, { fiscal_year_label: f.fiscal_year_label, budgeted: f.budgeted, actual: f.actual, note: f.note, code: f.code || null, name: f.name || null, estimated: f.estimated, reason: f.reason });
      else await api.post(`/api/budgets/history-entries/${e.id}/retire`, { reason: f.reason });
      onSaved();
    } catch (x) { setErr(x); }
  };
  const heading = title || (edit.mode === "correct" ? `Correct ${e.fiscal_year_label}` : `Retire ${e.fiscal_year_label}`);
  return (
    <Modal title={heading} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {edit.mode === "retire" ? (
          <p>The entry stops counting in the History and the Budget Review. It is kept (with your reason) and can't be deleted; the year can be entered again.</p>
        ) : (
          <>
            <Field label="Fiscal Year" hint="Include the year, for example FY2021."><input required maxLength={40} value={f.fiscal_year_label} onChange={(x) => setF({ ...f, fiscal_year_label: x.target.value })} /></Field>
            <div className="row fields">
              <Field label="Budgeted"><input required inputMode="decimal" maxLength={20} value={f.budgeted} onChange={(x) => setF({ ...f, budgeted: x.target.value })} /></Field>
              <Field label="Actual"><input required inputMode="decimal" maxLength={20} value={f.actual} onChange={(x) => setF({ ...f, actual: x.target.value })} /></Field>
            </div>
            {/* 2.3.0 (#390): an estimated year needs a note saying why (shown as the * footnote in reports) */}
            <label className="check"><input type="checkbox" checked={f.estimated} onChange={(x) => setF({ ...f, estimated: x.target.checked })} /> Estimated</label>
            <Field label={f.estimated ? "Note (required: why it is estimated)" : "Note (optional)"} hint={f.estimated ? "Printed as the footnote wherever the year is marked *." : "For example: from the 2021 treasurer's spreadsheet."}><input required={f.estimated} maxLength={500} value={f.note} onChange={(x) => setF({ ...f, note: x.target.value })} /></Field>
            <details className="year-name" open={!!(f.code || f.name)}>
              <summary>Called differently that year?</summary>
              <div className="row fields">
                <Field label="Code that year" hint={defaults?.code ? `Empty: ${defaults.code}` : undefined}><input maxLength={20} value={f.code} onChange={(x) => setF({ ...f, code: x.target.value })} /></Field>
                <Field label="Name that year" hint={defaults?.name ? `Empty: ${defaults.name}` : undefined}><input maxLength={120} value={f.name} onChange={(x) => setF({ ...f, name: x.target.value })} /></Field>
              </div>
            </details>
          </>
        )}
        {edit.mode !== "add" ? <Field label="Reason (required)"><input required maxLength={500} value={f.reason} onChange={(x) => setF({ ...f, reason: x.target.value })} /></Field> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">{edit.mode === "add" ? "Add" : edit.mode === "correct" ? "Save correction" : "Retire"}</button></div>
      </GuardedForm>
    </Modal>
  );
}

/** On a budget's History: the budget from before PennyWarden its line continues, with Link / Change / Unlink for
 * Budget Managers (on the earliest budget of the line, which carries the link). */
export function FormerLinkLine({ en, manage, onChanged }: { en: any; manage: boolean; onChanged: () => void }) {
  const [picking, setPicking] = useState(false);
  const [opts, setOpts] = useState<any[] | null>(null);
  const [pick, setPick] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const holder = en.holder;
  useEffect(() => {
    if (!picking) return;
    api.get(`/api/budgets/former/link-options${qs({ budget_id: holder.id })}`).then(setOpts, setErr);
  }, [picking]);
  const save = async (id: number | null) => {
    try { await api.put(`/api/budgets/${holder.id}/former-link`, { former_budget_id: id }); setPicking(false); onChanged(); } catch (x) { setErr(x); }
  };
  return (
    <div className="former-link" data-testid="former-link">
      <ErrorBox error={err} />
      <p>
        {en.former ? <>Before PennyWarden: continues <b>{en.former.label}</b>{!en.is_holder ? <> (through {holder.label})</> : null}.</>
          : <span className="muted">Not linked to a budget from before PennyWarden.</span>}
        {manage && !picking ? <>
          {" "}<button type="button" className="small" onClick={() => setPicking(true)}>{en.former ? "Change…" : "Link…"}</button>
          {en.former ? <> <button type="button" className="small" onClick={() => save(null)}>Unlink</button></> : null}
        </> : null}
      </p>
      {picking ? (
        <div className="row fields">
          <Field label={`Budget from before PennyWarden${!en.is_holder ? ` (linked from ${holder.label})` : ""}`}>
            <select aria-label="Budget from before PennyWarden" value={pick} onChange={(e) => setPick(e.target.value)} disabled={opts === null}>
              <option value="">— Choose —</option>
              {(opts || []).map((o) => <option key={o.id} value={o.id}>{o.label}{o.years ? ` (${o.years} ${o.years === 1 ? "year" : "years"})` : ""}</option>)}
            </select>
          </Field>
          <div className="actions left">
            <button type="button" className="primary" disabled={!pick} onClick={() => save(Number(pick))}>Link</button>
            <button type="button" onClick={() => setPicking(false)}>Cancel</button>
          </div>
          {opts && !opts.length ? <p className="muted small">None of the same type is free. Add one on Budgets → Before PennyWarden, or use Add an earlier year.</p> : null}
        </div>
      ) : null}
    </div>
  );
}
