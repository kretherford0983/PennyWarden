import { Fragment, useEffect, useState, type FormEvent } from "react";
import { api, money, qs } from "../api";
import { ErrorBox, Field, GrossBudgetNote, Loading, Modal, GuardedForm } from "../components";
import { useMe } from "../App";
import { useRouter } from "../router";
import { BudgetSection } from "./BudgetTable";
import { FormerBudgetsDialog, FormerLinkLine, YearForm } from "./FormerBudgets";

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
        {fys.length ? <button onClick={() => setModal({ kind: "former" })} title="Budgets as they were in your earlier spreadsheets, with their years">Before PennyWarden…</button> : null}
      </div>
      <ErrorBox error={err} />
      {!fys.length ? <p className="muted">No Fiscal Years exist yet.</p> : null}
      {fy?.status === "CLOSED" ? <div className="alert info">{fy.display_name} is closed; budgets are read-only.</div> : null}
      {tree ? (
        <>
          <BudgetSection title="Income" rows={tree.income} summary={tree.income_summary} fyStatus={fy.status} actions={actions} registerLinks onHistory={(r) => setModal({ kind: "history", row: r })} historyForAll={manage} />
          <BudgetSection title="Expense" rows={tree.expense} summary={tree.expense_summary} fyStatus={fy.status} actions={actions} registerLinks onHistory={(r) => setModal({ kind: "history", row: r })} historyForAll={manage} />
          <GrossBudgetNote />
          {tree.budget_zero ? (
            <p className="muted">Protected Budget 0 (non-budget activity such as transfers): inflows {money(tree.budget_zero.inflow)} · outflows {money(tree.budget_zero.outflow)}</p>
          ) : null}
        </>
      ) : fyId ? <Loading /> : null}
      {modal?.kind === "create" ? <BudgetForm fys={fys} fyId={fyId!} parent={modal.parent} onClose={() => setModal(null)} onSaved={done} /> : null}
      {modal?.kind === "edit" ? <BudgetEdit row={modal.row} canDelete={can("budget.delete") && fy?.status === "DRAFT"} onDelete={() => setModal({ kind: "reason", row: modal.row, action: "delete", title: `Delete ${modal.row.label}` })} onClose={() => setModal(null)} onSaved={done} /> : null}
      {modal?.kind === "history" ? <BudgetHistory row={modal.row} manage={manage} onClose={() => { setModal(null); load(); }} /> : null}
      {modal?.kind === "import-history" && fy ? <ImportHistory fy={fy} onClose={() => setModal(null)} onSaved={load} /> : null}
      {modal?.kind === "former" ? <FormerBudgetsDialog fys={fys} manage={manage} onClose={() => setModal(null)} onChanged={load} /> : null}
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
        ...continuesBody(cont),
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
        <Field label="Gross amount"><input required inputMode="decimal" pattern="\d+(\.\d{1,2})?" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <ContinuesField fyId={Number(f.fiscal_year_id)} budgetType={f.budget_type} subBudget={!!parent} value={cont} onChange={setCont} />
        <Field label="Notes"><textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Create</button></div>
      </GuardedForm>
    </Modal>
  );
}

function BudgetEdit({ row, onClose, onSaved, canDelete, onDelete }: any) {
  const [f, setF] = useState({ name: row.name, amount: row.amount, notes: row.notes || "" });
  const [cont, setCont] = useState(row.continues_former_budget_id ? `f:${row.continues_former_budget_id}` : row.continues_budget_id ? String(row.continues_budget_id) : "");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.patch(`/api/budgets/${row.id}`, { name: f.name, amount: f.amount, notes: f.notes || null, ...continuesBody(cont) });
      onSaved();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Edit ${row.label}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Name"><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Gross amount" hint="Other is recalculated automatically; sub-budgets may not exceed the parent."><input required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
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

/** The Continues choice as request fields: an earlier budget ("id"), a budget from before PennyWarden ("f:id"), or none
 * (2.2.0 #381: one predecessor, so each clears the other). */
function continuesBody(cont: string) {
  if (cont.startsWith("f:")) return { continues_budget_id: null, continues_former_budget_id: Number(cont.slice(2)) };
  return { continues_budget_id: cont ? Number(cont) : null, continues_former_budget_id: null };
}

/** 1.8.0 (#89): the earlier budget this one continues - budgets of earlier Fiscal Years, same type and level,
 * not already continued by another budget; grouped by Fiscal Year, newest first. 2.2.0 (#381): or a budget from
 * before PennyWarden of the same type (any level) that no other budget continues. */
function ContinuesField({ fyId, budgetType, subBudget, budgetId, value, onChange }: {
  fyId: number; budgetType: string; subBudget: boolean; budgetId?: number; value: string; onChange: (v: string) => void;
}) {
  const [groups, setGroups] = useState<any[] | null>(null);
  const [formers, setFormers] = useState<any[] | null>(null);
  useEffect(() => {
    setGroups(null);
    api.get(`/api/budgets/continue-options${qs({ fiscal_year_id: fyId, budget_type: budgetType, level: subBudget ? "sub-budget" : "budget", budget_id: budgetId })}`)
      .then((g: any[]) => setGroups(g), () => setGroups([]));
    api.get("/api/budgets/former")
      .then((l: any[]) => setFormers(l.filter((x) => !x.retired && x.budget_type === budgetType && (!x.continued_by || x.continued_by.id === budgetId))), () => setFormers([]));
  }, [fyId, budgetType, subBudget, budgetId]);
  useEffect(() => {
    if (!value || groups === null || formers === null) return;
    const ok = value.startsWith("f:") ? formers.some((x) => `f:${x.id}` === value) : groups.some((g) => g.options.some((o: any) => String(o.id) === value));
    if (!ok) onChange("");
  }, [groups, formers]);
  if (groups && formers && !groups.length && !formers.length) return null; // nothing earlier to continue
  return (
    <Field label="Continues" hint={subBudget ? "The sub-budget of an earlier Fiscal Year, or the budget from before PennyWarden, that this sub-budget continues (optional)."
      : "The budget of an earlier Fiscal Year, or from before PennyWarden, that this budget continues (optional). History then shows them together."}>
      <select aria-label="Continues budget" value={value} onChange={(e) => onChange(e.target.value)} disabled={groups === null || formers === null}>
        <option value="">— None —</option>
        {(groups || []).map((g) => (
          <optgroup key={g.fiscal_year.id} label={g.fiscal_year.display_name}>
            {g.options.map((o: any) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </optgroup>
        ))}
        {formers && formers.length ? (
          <optgroup label="Before PennyWarden">
            {formers.map((x) => <option key={`f${x.id}`} value={`f:${x.id}`}>Before PennyWarden - {x.label}</option>)}
          </optgroup>
        ) : null}
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
  const [edit, setEdit] = useState<any>(null);   // {mode: "add"} | {mode: "correct", e} | {mode: "retire", e} | {mode: "include"} | {mode: "retire-mark", m}
  const load = () => {
    api.get(`/api/budgets/${row.id}/history`).then(setH, setErr);
    api.get(`/api/budgets/${row.id}/history/entered`).then(setEn, setErr);
  };
  useEffect(load, [row.id]);
  const entries: any[] = en?.entries || [];
  const shown = entries.filter((x) => !x.retired);
  const retired = entries.filter((x) => x.retired);
  // 2.3.0 (#414): years its money was included in another budget, with the years before / in PennyWarden
  const marks: any[] = en?.inclusions || [];
  const markRow = (m: any) => (
    <tr key={`m${m.id}`} className="entered-row" data-testid="inclusion-row">
      <td>{m.fiscal_year_label}</td><td />
      <td>
        <i>Included in {m.included_in}</i>
        {m.note ? <div className="muted small">{m.note}</div> : null}
        {!m.counted ? <div className="muted small">Not shown: this budget's line has figures that year.</div> : null}
      </td>
      <td className="num muted">—</td><td className="num muted">—</td>
      {manage ? <td><button type="button" className="small" aria-label={`Retire the mark for ${m.fiscal_year_label}`} onClick={() => setEdit({ mode: "retire-mark", m })}>Retire</button></td> : null}
    </tr>
  );
  const before = marks.filter((m) => !m.retired && !m.in_pennywarden);
  const inPw = marks.filter((m) => !m.retired && m.in_pennywarden);
  const retiredMarks = marks.filter((m) => m.retired);
  return (
    <Modal title={`History of ${row.label}`} onClose={onClose} wide>
      <ErrorBox error={err} />
      {!h || !en ? (err ? null : <Loading />) : (
        <>
          <div className="table-wrap">
            <table className="table" aria-label="Budget history">
              <thead><tr><th>Fiscal Year</th><th>ID</th><th>Name</th><th className="num">Amount</th><th className="num">Actual</th>{manage ? <th /> : null}</tr></thead>
              <tbody>
                {before.filter((m) => !shown.length || m.year < shown[0].year).map(markRow)}
                {shown.map((x, i) => (
                  <tr key={`e${x.id ?? `s${i}`}`} className="entered-row">
                    <td>{x.fiscal_year_label}{x.estimated ? <span title={`Estimated: ${x.note || ""}`} data-testid="estimated-mark">*</span> : null} <span className="badge grey" title="Entered from earlier records, before PennyWarden">Entered</span></td>
                    {/* 2.2.0 (#381): the code and name the budget had that year (from before PennyWarden) */}
                    <td>{x.code_shown ? <span className="code">{x.code_shown}</span> : null}</td>
                    <td>
                      {x.name_shown ? <div>{x.name_shown}</div> : null}
                      {x.from_sub_budgets ? <i>sum of its sub-budgets</i> : x.note ? <div className="muted small">{x.note}</div> : null}
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
                {before.filter((m) => shown.length && m.year >= shown[0].year).map(markRow)}
                {inPw.filter((m) => !h.length || m.start_date < h[0].fiscal_year.start_date).map(markRow)}
                {h.map((x, hi) => (<Fragment key={x.id}>
                  {hi > 0 ? inPw.filter((m) => m.start_date > h[hi - 1].fiscal_year.start_date && m.start_date < x.fiscal_year.start_date).map(markRow) : null}
                  <tr key={x.id} className={x.this ? "current-row" : ""} aria-current={x.this ? "true" : undefined}>
                    <td>{x.fiscal_year.display_name}</td><td><span className="code">{x.code}</span></td>
                    <td>{x.this ? <b>{x.name}</b> : x.name}{["REJECTED", "INACTIVE"].includes(x.status) ? <span className="muted"> ({x.status.toLowerCase()})</span> : null}</td>
                    <td className="num">{money(x.amount)}</td><td className="num">{money(x.actual)}</td>{manage ? <td /> : null}
                  </tr>
                </Fragment>))}
              </tbody>
            </table>
          </div>
          {retiredMarks.length ? (
            <details className="retired-entries">
              <summary>Retired "included in" marks ({retiredMarks.length})</summary>
              <ul>{retiredMarks.map((m) => <li key={m.id}>{m.fiscal_year_label}: included in {m.included_in} — retired: {m.retire_reason}</li>)}</ul>
            </details>
          ) : null}
          {retired.length ? (
            <details className="retired-entries">
              <summary>Retired entries ({retired.length})</summary>
              <ul>{retired.map((x) => <li key={x.id}>{x.fiscal_year_label}: {money(x.budgeted)} budgeted, {money(x.actual)} actual — retired: {x.retire_reason}</li>)}</ul>
            </details>
          ) : null}
          <FormerLinkLine en={en} manage={manage} onChanged={load} />
          {manage && en.can_enter ? (
            <p className="hint">
              Years before PennyWarden{en.first_year ? <> (before FY{en.first_year})</> : null} can be entered from earlier records. They are labelled <i>Entered</i>, show in this History and the Budget Review, and never change actuals.
              {" "}<button type="button" className="small" onClick={() => setEdit({ mode: "add" })}>Add an earlier year</button>
            </p>
          ) : null}
        </>
      )}
      {edit?.mode === "include" ? <InclusionForm row={row} onBack={() => setEdit({ mode: "add" })} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} /> : null}
      {edit?.mode === "retire-mark" ? <RetireMark m={edit.m} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} /> : null}
      {edit && ["add", "correct", "retire"].includes(edit.mode) ? <YearForm title={edit.mode === "add" ? `Add an earlier year to ${row.label}` : undefined} addUrl={`/api/budgets/${row.id}/history/entered`} edit={edit}
                        onIncluded={edit.mode === "add" ? () => setEdit({ mode: "include" }) : undefined}
                        defaults={en?.former ? { code: en.former.default_code, name: en.former.default_name } : undefined}
                        onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} /> : null}
      <div className="actions"><button type="button" onClick={onClose}>Close</button></div>
    </Modal>
  );
}

/** 2.3.0 (#414): mark a year in which this budget's money was included in another budget (no figures of its own):
 * a Fiscal Year in PennyWarden with a budget of that year, or a year before PennyWarden with a budget from before
 * PennyWarden. Same type (Income/Expense), any level. Shown as "included in …" in the Budget Review. */
function InclusionForm({ row, onBack, onClose, onSaved }: any) {
  const [o, setO] = useState<any>(null);
  const [year, setYear] = useState("");            // a Fiscal Year id, or "before"
  const [label, setLabel] = useState("");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get(`/api/budgets/${row.id}/history/inclusion-options`).then(setO, setErr); }, [row.id]);
  const fy = o?.fiscal_years.find((y: any) => String(y.id) === year);
  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setErr(null);
    try {
      await api.post(`/api/budgets/${row.id}/history/inclusions`, year === "before"
        ? { fiscal_year_label: label, included_former_budget_id: Number(target), note: note || null }
        : { fiscal_year_id: Number(year), included_budget_id: Number(target), note: note || null });
      onSaved();
    } catch (x) { setErr(x); }
  };
  const targets: any[] = year === "before" ? (o?.formers || []) : (fy?.budgets || []);
  return (
    <Modal title={`Add an earlier year to ${row.label}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <fieldset className="choices">
          <label className="check"><input type="radio" name="year-kind" checked={false} onChange={onBack} /> Its figures that year</label>
          <label className="check"><input type="radio" name="year-kind" checked readOnly /> Its money was included in another budget that year</label>
        </fieldset>
        {!o ? (err ? null : <Loading />) : (
          <>
            <Field label="Year">
              <select required value={year} onChange={(x) => { setYear(x.target.value); setTarget(""); }}>
                <option value="">Choose…</option>
                {o.fiscal_years.map((y: any) => <option key={y.id} value={y.id}>{y.display_name}</option>)}
                <option value="before">An earlier year (before PennyWarden{o.first_year ? `, before FY${o.first_year}` : ""})</option>
              </select>
            </Field>
            {year === "before" ? <Field label="Fiscal Year" hint="Include the year, for example FY2021."><input required maxLength={40} value={label} onChange={(x) => setLabel(x.target.value)} /></Field> : null}
            {year ? (
              <Field label="Included in" hint="A budget of the same type (Income or Expense), at any level.">
                <select required value={target} onChange={(x) => setTarget(x.target.value)}>
                  <option value="">Choose…</option>
                  {targets.map((t: any) => <option key={t.id} value={t.id}>{t.label}</option>)}
                </select>
              </Field>
            ) : null}
            {year && !targets.length ? <p className="muted small">{year === "before" ? "No budgets from before PennyWarden of this type." : "No budgets of this type that year."}</p> : null}
            <Field label="Note (optional)"><input maxLength={500} value={note} onChange={(x) => setNote(x.target.value)} /></Field>
            <p className="hint">No amounts: the Budget Review shows <i>included in …</i> that year, and the year isn't counted in Avg.</p>
          </>
        )}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Add</button></div>
      </GuardedForm>
    </Modal>
  );
}

function RetireMark({ m, onClose, onSaved }: any) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    try { await api.post(`/api/budgets/history-inclusions/${m.id}/retire`, { reason }); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Retire the mark for ${m.fiscal_year_label}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <p>The Budget Review stops showing <i>included in {m.included_in}</i> that year. The mark is kept (with your reason) and can't be deleted; the year can be marked again.</p>
        <Field label="Reason (required)"><input required maxLength={500} value={reason} onChange={(x) => setReason(x.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Retire</button></div>
      </GuardedForm>
    </Modal>
  );
}

/** 2.2.0 (#284, #381): earlier years from a spreadsheet. Each row: a budget of this Fiscal Year (or none), the budget
 * as it was before PennyWarden (former code and name), the year and its figures. One import creates the budgets from
 * before PennyWarden, links them and enters the years; previewed before anything is saved. */
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
  const lineOf = (key: string, type: string | null) => (p?.lines || []).find((g: any) => g.key === key && (!type || g.budget_type === type));
  return (
    <Modal title="Import earlier years (before PennyWarden)" onClose={onClose} wide>
      {done ? (
        <>
          <div className="alert ok" role="status">
            {done.saved} {done.saved === 1 ? "year was" : "years were"} entered
            {done.former_budgets_created ? <>, {done.former_budgets_created} {done.former_budgets_created === 1 ? "budget" : "budgets"} from before PennyWarden created</> : null}
            {done.links_made ? <>, {done.links_made} {done.links_made === 1 ? "link" : "links"} made</> : null}.
          </div>
          <div className="actions"><button className="primary" type="button" onClick={onClose}>Done</button></div>
        </>
      ) : (
        <>
          <p>
            A CSV file from your earlier spreadsheets, one row per budget per year, with the columns <b>budget code, type,
            former code, former name, year, budgeted, actual, note, line, estimated</b>.
          </p>
          <ul className="small">
            <li><b>Budget code</b>: the budget of <b>{fy.display_name}</b> that continues it (a sub-budget, or <i>-00</i> for a parent's Other, works too). Leave it empty for a budget that no budget of PennyWarden continues; then <b>type</b> (Income or Expense) is needed.</li>
            <li><b>Former code</b> and <b>former name</b>: the budget as it was called that year (empty: the same as the budget). Rows with the same budget code are one budget; without a budget code, rows with the same former code are. Use <b>line</b> (any label) to keep a renumbered budget together.</li>
            <li>Only years before the first Fiscal Year in PennyWarden. Template rows you don't fill in are skipped.</li>
            <li><b>Estimated</b> (optional): <i>yes</i> for a figure that is an estimate — its <b>note</b> must then say why; empty or <i>no</i> otherwise.</li>
          </ul>
          <p><a className="button" href={`/api/budgets/history-entries/template${qs({ fiscal_year_id: fy.id })}`}>Download the template</a> <span className="hint">(this year's budgets, ready to fill in)</span></p>
          <ErrorBox error={err} />
          <Field label="CSV file"><input type="file" accept=".csv,text/csv" onChange={(e) => pick(e.target.files?.[0])} /></Field>
          <Field label="Or paste the CSV"><textarea rows={5} value={text} onChange={(e) => { setText(e.target.value); setP(null); }} /></Field>
          <div className="actions left"><button type="button" disabled={!text.trim() || busy} onClick={() => call("preview")}>Preview</button></div>
          {p ? (
            <>
              <p role="status">
                {p.counts.MATCHED} will be saved · {p.counts.DUPLICATE} duplicate · {p.counts.REFUSED} refused
                {p.new_former_budgets ? <> · {p.new_former_budgets} new {p.new_former_budgets === 1 ? "budget" : "budgets"} from before PennyWarden</> : null}
                {p.new_links ? <> · {p.new_links} new {p.new_links === 1 ? "link" : "links"}</> : null}. Nothing is saved until you choose Import.
              </p>
              {p.lines.some((g: any) => g.years) ? (
                <div className="table-wrap">
                  <table className="table compact" aria-label="Budgets in the import">
                    <thead><tr><th>Before PennyWarden</th><th>Years</th><th>Continued by</th></tr></thead>
                    <tbody>{p.lines.filter((g: any) => g.years).map((g: any, i: number) => (
                      <tr key={i}>
                        <td><span className="code">{g.former_code}</span> {g.former_name} {g.action === "NEW" ? <span className="badge grey">New</span> : null}</td>
                        <td>{g.years}</td>
                        <td>{g.link ? <>{g.link.label}{g.link_action === "NEW" ? <span className="badge grey" style={{ marginLeft: 6 }}>New link</span> : null}</> : <span className="muted">Not continued</span>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : null}
              <div className="table-wrap">
                <table className="table compact" aria-label="Import preview">
                  <thead><tr><th>Line</th><th>Year</th><th>Budget</th><th>Before PennyWarden</th><th className="num">Budgeted</th><th className="num">Actual</th><th>Result</th></tr></thead>
                  <tbody>{p.rows.map((r: any) => {
                    const g = r.group ? lineOf(r.group, r.group.startsWith("former ") ? r.type : null) : null;
                    return (
                      <tr key={r.line} className={r.status === "MATCHED" ? "" : "muted"}>
                        <td>{r.line}</td><td>{r.year_label}</td><td>{r.code} {r.budget_name || ""}</td>
                        <td>{r.former_code || r.former_name ? <>{r.former_code} {r.former_name}</> : g ? <span className="muted">{g.former_code} {g.former_name}</span> : null}</td>
                        <td className="num">{r.status !== "REFUSED" ? money(r.budgeted) : r.budgeted}</td><td className="num">{r.status !== "REFUSED" ? money(r.actual) : r.actual}</td>
                        <td>{word[r.status]}{r.reason ? <div className="small">{r.reason}</div> : null}</td>
                      </tr>
                    );
                  })}</tbody>
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
