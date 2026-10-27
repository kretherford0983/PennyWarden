import { useEffect, useState, type FormEvent } from "react";
import { api, money, qs } from "../api";
import { ErrorBox, Field, Loading, Modal, GuardedForm } from "../components";
import { useMe } from "../App";
import { useRouter } from "../router";
import { BudgetSection } from "./BudgetTable";

export default function Budgets() {
  const { can } = useMe();
  const { search } = useRouter();
  const [fys, setFys] = useState<any[] | null>(null);
  const [fyId, setFyId] = useState<number | null>(null);
  const [tree, setTree] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [modal, setModal] = useState<any>(null);
  useEffect(() => {
    api.get("/api/fiscal-years").then((l: any[]) => {
      setFys(l);
      const want = Number(new URLSearchParams(search).get("fiscal_year_id"));
      const today = new Date().toISOString().slice(0, 10);
      const cur = l.find((f) => f.id === want) || l.find((f) => f.start_date <= today && f.end_date >= today && f.status !== "CLOSED") || l[l.length - 1];
      setFyId(cur ? cur.id : null);
    }, setErr);
  }, []);
  const load = () => fyId && api.get(`/api/budgets${qs({ fiscal_year_id: fyId })}`).then(setTree, setErr);
  useEffect(() => {
    setTree(null);
    load();
  }, [fyId]);
  if (!fys) return <><ErrorBox error={err} /><Loading /></>;
  const manage = can("budget.manage");
  const fy = fys.find((f) => f.id === fyId);
  const actions = manage ? {
    onEdit: (r: any) => setModal({ kind: "edit", row: r }),
    onAddChild: (r: any) => setModal({ kind: "create", parent: r }),
    onReject: (r: any) => setModal({ kind: "reason", row: r, action: "reject", title: `Reject ${r.label}` }),
    onInactivate: (r: any) => setModal({ kind: "reason", row: r, action: "inactivate", title: `Inactivate ${r.label}` }),
    onUnlock: (r: any) => setModal({ kind: "reason", row: r, action: "unlock", title: `Unlock ${r.label}` }),
    onLock: async (r: any) => { try { await api.post(`/api/budgets/${r.id}/lock`); load(); } catch (e) { setErr(e); } },
  } : undefined;
  const done = () => { setModal(null); load(); };
  return (
    <div>
      <div className="page-head">
        <h1>Budgets</h1>
        <Field label="Fiscal Year">
          <select aria-label="Budget Fiscal Year filter" value={fyId ?? ""} onChange={(e) => setFyId(Number(e.target.value))}>
            {fys.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </Field>
        {manage && fy && fy.status !== "CLOSED" ? <button className="primary" onClick={() => setModal({ kind: "create" })}>New budget</button> : null}
        {manage && fy ? <button onClick={() => setModal({ kind: "import-history" })} title="Budgeted and actual figures of years before PennyWarden, from a CSV file">Import earlier years…</button> : null}
      </div>
      <ErrorBox error={err} />
      {!fys.length ? <p className="muted">No Fiscal Years exist yet.</p> : null}
      {fy?.status === "CLOSED" ? <div className="alert info">{fy.display_name} is closed; budgets are read-only.</div> : null}
      {tree ? (
        <>
          <BudgetSection title="Income" rows={tree.income} summary={tree.income_summary} fyStatus={fy.status} actions={actions} registerLinks onHistory={(r) => setModal({ kind: "history", row: r })} historyForAll={manage} />
          <BudgetSection title="Expense" rows={tree.expense} summary={tree.expense_summary} fyStatus={fy.status} actions={actions} registerLinks onHistory={(r) => setModal({ kind: "history", row: r })} historyForAll={manage} />
          {tree.budget_zero ? (
            <p className="muted">Protected Budget 0 (non-budget activity such as transfers): inflows {money(tree.budget_zero.inflow)} · outflows {money(tree.budget_zero.outflow)}</p>
          ) : null}
        </>
      ) : fyId ? <Loading /> : null}
      {modal?.kind === "create" ? <BudgetForm fys={fys} fyId={fyId!} parent={modal.parent} onClose={() => setModal(null)} onSaved={done} /> : null}
      {modal?.kind === "edit" ? <BudgetEdit row={modal.row} canDelete={can("budget.delete") && fy?.status === "DRAFT"} onDelete={() => setModal({ kind: "reason", row: modal.row, action: "delete", title: `Delete ${modal.row.label}` })} onClose={() => setModal(null)} onSaved={done} /> : null}
      {modal?.kind === "history" ? <BudgetHistory row={modal.row} manage={manage} onClose={() => { setModal(null); load(); }} /> : null}
      {modal?.kind === "import-history" && fy ? <ImportHistory fy={fy} onClose={() => setModal(null)} onSaved={load} /> : null}
      {modal?.kind === "reason" ? <ReasonForm {...modal} onClose={() => setModal(null)} onSaved={done} /> : null}
    </div>
  );
}

function BudgetForm({ fys, fyId, parent, onClose, onSaved }: any) {
  const [f, setF] = useState({ fiscal_year_id: fyId, code: "", name: "", budget_type: parent?.budget_type || "EXPENSE", amount: "", notes: "" });
  const [cont, setCont] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/api/budgets", {
        fiscal_year_id: Number(f.fiscal_year_id), code: f.code, name: f.name, amount: f.amount, notes: f.notes || null,
        continues_budget_id: cont ? Number(cont) : null,
        ...(parent ? { parent_budget_id: parent.id } : { budget_type: f.budget_type }),
      });
      onSaved();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={parent ? `New sub-budget of ${parent.label}` : "New budget"} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {!parent ? (
          <Field label="Fiscal Year">
            <select aria-label="Create Budget Fiscal Year" value={f.fiscal_year_id} onChange={(e) => setF({ ...f, fiscal_year_id: Number(e.target.value) })}>
              {fys.filter((x: any) => x.status !== "CLOSED").map((x: any) => <option key={x.id} value={x.id}>{x.label}</option>)}
            </select>
          </Field>
        ) : <p>Parent: <b>{parent.label}</b> · Other currently {money(parent.other_amount)}</p>}
        <Field label={parent ? "Sub-budget code (e.g. 01)" : "Budget code (e.g. 1000)"}><input required pattern="[A-Za-z0-9]{1,10}" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
        <Field label="Name"><input required maxLength={120} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        {!parent ? (
          <Field label="Type"><select value={f.budget_type} onChange={(e) => setF({ ...f, budget_type: e.target.value })}><option value="INCOME">Income</option><option value="EXPENSE">Expense</option></select></Field>
        ) : null}
        <Field label="Amount"><input required inputMode="decimal" pattern="\d+(\.\d{1,2})?" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <ContinuesField fyId={Number(f.fiscal_year_id)} budgetType={f.budget_type} subBudget={!!parent} value={cont} onChange={setCont} />
        <Field label="Notes"><textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Create</button></div>
      </GuardedForm>
    </Modal>
  );
}

function BudgetEdit({ row, onClose, onSaved, canDelete, onDelete }: any) {
  const [f, setF] = useState({ name: row.name, amount: row.amount, notes: row.notes || "" });
  const [cont, setCont] = useState(row.continues_budget_id ? String(row.continues_budget_id) : "");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.patch(`/api/budgets/${row.id}`, { name: f.name, amount: f.amount, notes: f.notes || null,
                                                continues_budget_id: cont ? Number(cont) : null });
      onSaved();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Edit ${row.label}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Name"><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Amount" hint="Other is recalculated automatically; sub-budgets may not exceed the parent."><input required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <ContinuesField fyId={row.fiscal_year_id} budgetType={row.budget_type} subBudget={!!row.parent_budget_id} budgetId={row.id} value={cont} onChange={setCont} />
        <Field label="Notes"><textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <div className="actions">
          {/* 1.7.3 (#52): Budget Admins - red, set apart from Save / Cancel */}
          {canDelete && !row.system_managed ? <button type="button" className="danger delete-apart" onClick={onDelete}>Delete budget…</button> : null}
          <button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button>
        </div>
      </GuardedForm>
    </Modal>
  );
}

function ReasonForm({ row, action, title, onClose, onSaved }: any) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.post(`/api/budgets/${row.id}/${action}`, { reason });
      onSaved();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={title} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {action === "reject" ? <p>A rejected budget's allowed amount becomes 0. Existing allocations are preserved.</p> : null}
        {action === "unlock" ? <p>Unlocking permits an authorized amendment and is audited.</p> : null}
        {action === "delete" ? (
          <div className="alert warn" role="alert">
            <b>The budget will be deleted.</b> It disappears from the Budgets page, the budget lists and the totals, and
            it will not be copied into a new Fiscal Year. Auditors can still see it, with your reason. This cannot be
            undone. A budget with Register allocations or sub-budgets cannot be deleted.
          </div>
        ) : null}
        <Field label="Reason (required)"><textarea required value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className={`primary${action === "delete" ? " danger" : ""}`} type="submit" disabled={!reason.trim()}>{action === "delete" ? "Delete budget" : "Confirm"}</button></div>
      </GuardedForm>
    </Modal>
  );
}

/** 1.8.0 (#89): the earlier budget this one continues - budgets of earlier Fiscal Years, same type and level,
 * not already continued by another budget; grouped by Fiscal Year, newest first. */
function ContinuesField({ fyId, budgetType, subBudget, budgetId, value, onChange }: {
  fyId: number; budgetType: string; subBudget: boolean; budgetId?: number; value: string; onChange: (v: string) => void;
}) {
  const [groups, setGroups] = useState<any[] | null>(null);
  useEffect(() => {
    setGroups(null);
    api.get(`/api/budgets/continue-options${qs({ fiscal_year_id: fyId, budget_type: budgetType, level: subBudget ? "sub-budget" : "budget", budget_id: budgetId })}`)
      .then((g: any[]) => {
        setGroups(g);
        if (value && !g.some((x) => x.options.some((o: any) => String(o.id) === value))) onChange("");
      }, () => setGroups([]));
  }, [fyId, budgetType, subBudget, budgetId]);
  if (groups && !groups.length) return null; // nothing earlier to continue
  return (
    <Field label="Continues" hint={subBudget ? "The sub-budget of an earlier Fiscal Year that this sub-budget continues (optional)."
      : "The budget of an earlier Fiscal Year that this budget continues (optional). History then shows them together."}>
      <select aria-label="Continues budget" value={value} onChange={(e) => onChange(e.target.value)} disabled={groups === null}>
        <option value="">— None —</option>
        {(groups || []).map((g) => (
          <optgroup key={g.fiscal_year.id} label={g.fiscal_year.display_name}>
            {g.options.map((o: any) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </optgroup>
        ))}
      </select>
    </Field>
  );
}

/** 1.8.0 (#89): the budget's lineage across Fiscal Years, oldest first. 2.2.0 (#284): with the years before
 * PennyWarden entered by a Budget Manager (Entered), who can add, correct and retire them here. */
function BudgetHistory({ row, onClose, manage }: any) {
  const [h, setH] = useState<any[] | null>(null);
  const [en, setEn] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [edit, setEdit] = useState<any>(null);   // {mode: "add"} | {mode: "correct", e} | {mode: "retire", e}
  const load = () => {
    api.get(`/api/budgets/${row.id}/history`).then(setH, setErr);
    api.get(`/api/budgets/${row.id}/history/entered`).then(setEn, setErr);
  };
  useEffect(load, [row.id]);
  const entries: any[] = en?.entries || [];
  const shown = entries.filter((x) => !x.retired);
  const retired = entries.filter((x) => x.retired);
  return (
    <Modal title={`History of ${row.label}`} onClose={onClose} wide>
      <ErrorBox error={err} />
      {!h || !en ? (err ? null : <Loading />) : (
        <>
          <div className="table-wrap">
            <table className="table" aria-label="Budget history">
              <thead><tr><th>Fiscal Year</th><th>ID</th><th>Name</th><th className="num">Amount</th><th className="num">Actual</th>{manage ? <th /> : null}</tr></thead>
              <tbody>
                {shown.map((x, i) => (
                  <tr key={`e${x.id ?? `s${i}`}`} className="entered-row">
                    <td>{x.fiscal_year_label} <span className="badge grey" title="Entered from earlier records, before PennyWarden">Entered</span></td>
                    <td />
                    <td>
                      {x.from_sub_budgets ? <i>sum of its sub-budgets</i> : x.note ? <span className="muted">{x.note}</span> : null}
                      {!x.counted ? <div className="muted small">Not counted: a Fiscal Year in PennyWarden covers this year.</div> : null}
                      {x.mismatch ? <div className="muted small" data-testid="history-mismatch">Its sub-budgets add up to {money(x.mismatch.budgeted)} budgeted, {money(x.mismatch.actual)} actual.</div> : null}
                    </td>
                    <td className="num">{money(x.budgeted)}</td><td className="num">{money(x.actual)}</td>
                    {manage ? <td>{x.id ? <span className="row-buttons">
                      <button type="button" className="small" aria-label={`Correct ${x.fiscal_year_label}`} onClick={() => setEdit({ mode: "correct", e: x })}>Correct</button>
                      <button type="button" className="small" aria-label={`Retire ${x.fiscal_year_label}`} onClick={() => setEdit({ mode: "retire", e: x })}>Retire</button>
                    </span> : null}</td> : null}
                  </tr>
                ))}
                {h.map((x) => (
                  <tr key={x.id} className={x.this ? "current-row" : ""} aria-current={x.this ? "true" : undefined}>
                    <td>{x.fiscal_year.display_name}</td><td><span className="code">{x.code}</span></td>
                    <td>{x.this ? <b>{x.name}</b> : x.name}{["REJECTED", "INACTIVE"].includes(x.status) ? <span className="muted"> ({x.status.toLowerCase()})</span> : null}</td>
                    <td className="num">{money(x.amount)}</td><td className="num">{money(x.actual)}</td>{manage ? <td /> : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {retired.length ? (
            <details className="retired-entries">
              <summary>Retired entries ({retired.length})</summary>
              <ul>{retired.map((x) => <li key={x.id}>{x.fiscal_year_label}: {money(x.budgeted)} budgeted, {money(x.actual)} actual — retired: {x.retire_reason}</li>)}</ul>
            </details>
          ) : null}
          {manage && en.can_enter ? (
            <p className="hint">
              Years before PennyWarden{en.first_year ? <> (before FY{en.first_year})</> : null} can be entered from earlier records. They are labelled <i>Entered</i>, show in this History and the Budget Review, and never change actuals.
              {" "}<button type="button" className="small" onClick={() => setEdit({ mode: "add" })}>Add an earlier year</button>
            </p>
          ) : null}
        </>
      )}
      {edit ? <EnteredYearForm row={row} edit={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} /> : null}
      <div className="actions"><button type="button" onClick={onClose}>Close</button></div>
    </Modal>
  );
}

/** 2.2.0 (#284): add, correct (reason required) or retire (reason required) an entered year. */
function EnteredYearForm({ row, edit, onClose, onSaved }: any) {
  const e = edit.e || {};
  const [f, setF] = useState({ fiscal_year_label: e.fiscal_year_label || "", budgeted: e.budgeted || "", actual: e.actual || "", note: e.note || "", reason: "" });
  const [err, setErr] = useState<unknown>(null);
  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setErr(null);
    try {
      if (edit.mode === "add") await api.post(`/api/budgets/${row.id}/history/entered`, { fiscal_year_label: f.fiscal_year_label, budgeted: f.budgeted, actual: f.actual, note: f.note || null });
      else if (edit.mode === "correct") await api.patch(`/api/budgets/history-entries/${e.id}`, { fiscal_year_label: f.fiscal_year_label, budgeted: f.budgeted, actual: f.actual, note: f.note, reason: f.reason });
      else await api.post(`/api/budgets/history-entries/${e.id}/retire`, { reason: f.reason });
      onSaved();
    } catch (x) { setErr(x); }
  };
  const title = edit.mode === "add" ? `Add an earlier year to ${row.label}` : edit.mode === "correct" ? `Correct ${e.fiscal_year_label}` : `Retire ${e.fiscal_year_label}`;
  return (
    <Modal title={title} onClose={onClose}>
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
            <Field label="Note (optional)" hint="For example: from the 2021 treasurer's spreadsheet."><input maxLength={500} value={f.note} onChange={(x) => setF({ ...f, note: x.target.value })} /></Field>
          </>
        )}
        {edit.mode !== "add" ? <Field label="Reason (required)"><input required maxLength={500} value={f.reason} onChange={(x) => setF({ ...f, reason: x.target.value })} /></Field> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">{edit.mode === "add" ? "Add" : edit.mode === "correct" ? "Save correction" : "Retire"}</button></div>
      </GuardedForm>
    </Modal>
  );
}

/** 2.2.0 (#284): earlier years from a spreadsheet - year, budget code, budgeted, actual, note; matched on this Fiscal
 * Year's codes and previewed before anything is saved. */
function ImportHistory({ fy, onClose, onSaved }: any) {
  const [text, setText] = useState("");
  const [p, setP] = useState<any>(null);
  const [done, setDone] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const pick = async (file: File | undefined) => {
    setP(null); setErr(null);
    if (file) setText(await file.text());
  };
  const call = async (what: "preview" | "import") => {
    setBusy(true); setErr(null);
    try {
      const r = await api.post(`/api/budgets/history-entries/${what}`, { fiscal_year_id: fy.id, csv: text });
      if (what === "preview") setP(r); else { setDone(r); onSaved(); }
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const word: Record<string, string> = { MATCHED: "Will be saved", REFUSED: "Refused", DUPLICATE: "Duplicate" };
  return (
    <Modal title="Import earlier years (before PennyWarden)" onClose={onClose} wide>
      {done ? (
        <><div className="alert ok" role="status">{done.saved} {done.saved === 1 ? "year was" : "years were"} entered.</div><div className="actions"><button className="primary" type="button" onClick={onClose}>Done</button></div></>
      ) : (
        <>
          <p>A CSV file with the columns <b>year, budget code, budgeted, actual, note</b> — one row per budget per year — from your earlier spreadsheets. Codes are matched on the budgets of <b>{fy.display_name}</b>; a parent's figures can be entered on the parent, its sub-budgets, or both. Only years before the first Fiscal Year in PennyWarden are accepted.</p>
          <p><a className="button" href={`/api/budgets/history-entries/template${qs({ fiscal_year_id: fy.id })}`}>Download the template</a> <span className="hint">(this year's budget codes, ready to fill in)</span></p>
          <ErrorBox error={err} />
          <Field label="CSV file"><input type="file" accept=".csv,text/csv" onChange={(e) => pick(e.target.files?.[0])} /></Field>
          <Field label="Or paste the CSV"><textarea rows={5} value={text} onChange={(e) => { setText(e.target.value); setP(null); }} /></Field>
          <div className="actions left"><button type="button" disabled={!text.trim() || busy} onClick={() => call("preview")}>Preview</button></div>
          {p ? (
            <>
              <p role="status">{p.counts.MATCHED} will be saved · {p.counts.DUPLICATE} duplicate · {p.counts.REFUSED} refused. Nothing is saved until you choose Import.</p>
              <div className="table-wrap">
                <table className="table compact" aria-label="Import preview">
                  <thead><tr><th>Line</th><th>Year</th><th>Budget</th><th className="num">Budgeted</th><th className="num">Actual</th><th>Result</th></tr></thead>
                  <tbody>{p.rows.map((r: any) => (
                    <tr key={r.line} className={r.status === "MATCHED" ? "" : "muted"}>
                      <td>{r.line}</td><td>{r.year_label}</td><td>{r.code} {r.budget_name || ""}</td>
                      <td className="num">{r.status !== "REFUSED" ? money(r.budgeted) : r.budgeted}</td><td className="num">{r.status !== "REFUSED" ? money(r.actual) : r.actual}</td>
                      <td>{word[r.status]}{r.reason ? <div className="small">{r.reason}</div> : null}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </>
          ) : null}
          <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="button" disabled={!p || !p.counts.MATCHED || busy} onClick={() => call("import")}>Import {p ? p.counts.MATCHED : ""} {p && p.counts.MATCHED === 1 ? "year" : "years"}</button></div>
        </>
      )}
    </Modal>
  );
}
