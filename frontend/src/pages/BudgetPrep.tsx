// 2.1.0 (#257) Budget Prep report and (#261) the Fiscal Year Planning Sheet - Budget Managers only.
// Both use the same projection rule and the same per-user, per-budget projection choices.
import { Fragment, useEffect, useState } from "react";
import { api, money, qs } from "../api";
import { BudgetState, ErrorBox, Field, Loading, Modal } from "../components";

const today = () => new Date().toISOString().slice(0, 10);

function pctText(p: string | null | undefined) {
  return p === null || p === undefined ? "n/a" : `${p.replace("-", "")}%`;
}

/** "$450.00 under (50.0%)" - over/under in words, never by colour only. */
export function diffText(d: string | null | undefined, p: string | null | undefined) {
  if (d === null || d === undefined) return "";
  if (Number(d) === 0) return "on budget";
  return `${money(d.replace("-", ""))} ${d.startsWith("-") ? "under" : "over"} (${pctText(p)})`;
}

/** The budgets that can be projected or left unprojected (a budget without sub-budgets, or each sub-budget). */
export function ProjectionChoices({ fyId, onSaved }: { fyId: string | number; onSaved?: () => void }) {
  const [d, setD] = useState<any>(null);
  const [edit, setEdit] = useState<Record<number, boolean>>({});
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const load = () => api.get(`/api/reports/budget-prep/projection-choices${qs({ fiscal_year_id: fyId })}`).then((x) => { setD(x); setEdit({}); }, setErr);
  useEffect(() => { setD(null); load(); }, [fyId]);
  if (!d) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const rows = [...d.income.map((x: any) => ({ ...x, sec: "Income" })), ...d.expense.map((x: any) => ({ ...x, sec: "Expense" }))];
  const value = (r: any) => (r.budget_id in edit ? edit[r.budget_id] : r.project);
  const dirty = Object.keys(edit).length > 0;
  const save = async (reset = false) => {
    setBusy(true); setErr(null); setSaved(false);
    try {
      const choices = reset ? [] : Object.entries(edit).map(([id, project]) => ({ budget_id: Number(id), project }));
      setD(await api.put("/api/reports/budget-prep/projection-choices", { fiscal_year_id: Number(fyId), choices, reset }));
      setEdit({}); setSaved(true); onSaved?.();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <fieldset className="projection-choices">
      <legend>Projected budgets</legend>
      <p className="hint">Untick a budget known to be complete — for example one tracking a finished fundraiser that will receive nothing more. It then shows <i>Complete: no projection</i>. Your choices are remembered for this Fiscal Year.</p>
      <ErrorBox error={err} />
      <table className="table compact">
        <thead><tr><th>Project</th><th>Budget</th><th>Note</th></tr></thead>
        <tbody>
          {(["Income", "Expense"] as const).map((sec) => {
            const list = rows.filter((r: any) => r.sec === sec);
            return list.length ? (
              <Fragment key={sec}>
                <tr className="section-row"><th colSpan={3}>{sec}</th></tr>
                {list.map((r: any) => (
                  <tr key={r.budget_id}>
                    <td>{r.choosable ? <input type="checkbox" aria-label={`Project ${r.code} ${r.name}`} checked={value(r)} onChange={(e) => setEdit({ ...edit, [r.budget_id]: e.target.checked })} /> : null}</td>
                    <td className={r.level === "sub" ? "indent" : ""}>{r.code} {r.name}</td>
                    <td className="muted">{!r.choosable ? "sum of its sub-budgets" : r.complete_fundraisers?.length ? `finished fundraiser: ${r.complete_fundraisers.join(", ")}` : r.saved ? "your choice" : ""}</td>
                  </tr>
                ))}
              </Fragment>
            ) : null;
          })}
        </tbody>
      </table>
      <div className="actions left">
        <button className="primary" disabled={!dirty || busy} onClick={() => save(false)}>Save projection choices</button>
        <button disabled={busy} onClick={() => save(true)}>Back to defaults</button>
        {saved && !dirty ? <span className="ok-text" role="status">Saved.</span> : null}
      </div>
    </fieldset>
  );
}

function Cmp({ c, word = "Actual" }: { c: any; word?: string }) {
  if (!c) return <span className="muted" title="No linked budget that year">—</span>;
  return (
    <div className="cmp">
      <div>Budgeted {money(c.budgeted)}</div>
      <div>{word} {money(c.actual)}</div>
      <div>{diffText(c.difference, c.difference_pct)}</div>
      {c.renumbered || (c.status && c.status !== "APPROVED") ? <div className="muted small">{[c.renumbered ? c.code : null, c.status && c.status !== "APPROVED" ? c.status.charAt(0) + c.status.slice(1).toLowerCase() : null].filter(Boolean).join(" · ")}</div> : null}
    </div>
  );
}

function Proj({ p }: { p: any }) {
  if (!p) return null;
  if (p.state === "NOT_PROJECTED") return <div className="cmp"><i>Complete: no projection</i><div>YTD {money(p.projected)}</div></div>;
  if (p.state === "TOO_EARLY") return <i>too early to project</i>;
  const word = p.state === "ROLLUP" ? "sum of sub-budgets" : p.state === "YEAR_ENDED" ? "year ended: actual" : "projected";
  return <div className="cmp"><div>{money(p.projected)}</div><div>{diffText(p.difference, p.difference_pct)}</div><div className="muted small">{word}</div></div>;
}

function Next({ n }: { n: any }) {
  if (!n) return <span className="muted">—</span>;
  const ch = Number(n.change) === 0 ? "no change" : `${n.change.startsWith("-") ? "−" : "+"}${money(n.change.replace("-", ""))} (${pctText(n.change_pct)})`;
  return <div className="cmp"><div>{n.code} · {n.status.charAt(0) + n.status.slice(1).toLowerCase()}</div><div>{money(n.amount)}</div><div>change {ch}</div></div>;
}

export default function BudgetPrep({ fys }: { fys: any[] }) {
  const t = today();
  const cur = fys.find((f) => f.start_date <= t && f.end_date >= t) || fys[fys.length - 1];
  const [f, setF] = useState({ fiscal_year_id: cur ? String(cur.id) : "", years: "3", projected: false, include_next: false, budget: "", as_of: t });
  const [data, setData] = useState<any>(null);
  const [opts, setOpts] = useState<any[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!f.fiscal_year_id) return;
    setData(null);
    api.get(`/api/reports/budget-prep/projection-choices${qs({ fiscal_year_id: f.fiscal_year_id })}`).then((d) => setOpts([...d.income, ...d.expense]), () => setOpts([]));
  }, [f.fiscal_year_id]);
  const [kind, id] = f.budget ? f.budget.split(":") : ["", ""];
  const params = (format: string, download = false) => ({
    fiscal_year_id: f.fiscal_year_id, years: f.years, projected: f.projected || null, include_next: f.include_next || null,
    budget_id: kind === "b" ? id : null, parent_budget_id: kind === "p" ? id : null, as_of: f.as_of || null,
    format: format === "json" ? null : format, download: download || null,
  });
  const url = (format: string, download = false) => `/api/reports/budget-prep${qs(params(format, download))}`;
  const run = async () => {
    setBusy(true); setErr(null);
    try { setData(await api.get(url("json"))); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <section className="card">
      <h2 className="no-print">Budget Prep report</h2>
      <p className="no-print">Each budget of the Fiscal Year with its history over earlier years (following the budget continuation links, so a renumbered budget stays on one line), budgeted against actual, the year-to-date actual and, optionally, a projection to the year end and next year's continuing budget. For Budget Managers.</p>
      <div className="report-options no-print">
        <Field label="Fiscal Year">
          <select aria-label="Budget Prep Fiscal Year" value={f.fiscal_year_id} onChange={(e) => setF({ ...f, fiscal_year_id: e.target.value, budget: "" })}>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
          </select>
        </Field>
        <Field label="Prior years">
          <select value={f.years} onChange={(e) => setF({ ...f, years: e.target.value })}>
            {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
            <option value="-1">All linked years</option>
          </select>
        </Field>
        <Field label="Budgets">
          <select value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value })}>
            <option value="">All budgets</option>
            {opts.filter((o) => o.level === "parent").map((o) => <option key={`p${o.budget_id}`} value={`p:${o.budget_id}`}>{o.code} {o.name} and its sub-budgets</option>)}
            {opts.map((o) => <option key={`b${o.budget_id}`} value={`b:${o.budget_id}`}>Only {o.code} {o.name}</option>)}
          </select>
        </Field>
        <Field label="Actuals as of"><input type="date" value={f.as_of} onChange={(e) => setF({ ...f, as_of: e.target.value })} /></Field>
        <label className="check"><input type="checkbox" checked={f.projected} onChange={(e) => setF({ ...f, projected: e.target.checked })} /> Projected column</label>
        <label className="check"><input type="checkbox" checked={f.include_next} onChange={(e) => setF({ ...f, include_next: e.target.checked })} /> Next year's budget</label>
        <button className="primary" onClick={run} disabled={!f.fiscal_year_id || busy}>{busy ? "Running…" : "Run report"}</button>
      </div>
      {f.projected && f.fiscal_year_id ? <ProjectionChoices fyId={f.fiscal_year_id} onSaved={() => data && run()} /> : null}
      <ErrorBox error={err} />
      {data ? <BudgetPrepTable data={data} url={url} /> : null}
    </section>
  );
}

function BudgetPrepTable({ data, url }: { data: any; url: (format: string, download?: boolean) => string }) {
  const cols = data.years.length + 2 + (data.projected ? 1 : 0) + (data.include_next ? 1 : 0);
  return (
    <div className="budget-prep">
      <h2>Budget Prep — {data.fiscal_year.display_name}</h2>
      <p>Actuals year-to-date as of {data.as_of}. Prior years shown: {data.years.length} of {data.available_years}. Difference = actual − budgeted; n/a when nothing was budgeted.{data.projected ? ` Projected = YTD ÷ elapsed months × months in the year (${data.projection_basis.elapsed_months} of ${data.projection_basis.months} months elapsed).` : ""}</p>
      <div className="actions left no-print">
        <a className="button primary" href={url("pdf")} target="_blank" rel="noopener">Open PDF</a>
        <a className="button" href={url("pdf", true)}>Download PDF</a>
        <a className="button" href={url("csv")}>Download CSV</a>
      </div>
      <div className="table-scroll">
        <table className="table compact">
          <thead>
            <tr>
              <th>Budget</th>
              {data.years.map((y: any) => <th key={y.id}>{y.display_name}<div className="muted small">budgeted · actual · difference</div></th>)}
              <th>{data.fiscal_year.display_name} (current)<div className="muted small">budgeted · actual YTD · difference</div></th>
              {data.projected ? <th>Projected to {data.fiscal_year.end_date}</th> : null}
              {data.include_next ? <th>{data.next_fiscal_year ? data.next_fiscal_year.display_name : "Next year"}<div className="muted small">continuing budget · change</div></th> : null}
            </tr>
          </thead>
          <tbody>
            {(["income", "expense"] as const).map((sec) => data[sec].length ? (
              <Fragment key={sec}>
                <tr className="section-row"><th colSpan={cols}>{sec === "income" ? "Income" : "Expense"}</th></tr>
                {data[sec].map((r: any) => (
                  <tr key={r.id} className={r.level === "parent" ? "parent-row" : ""}>
                    <td className={r.level === "sub" ? "indent" : ""}>{r.level === "parent" ? <b>{r.code} {r.name}</b> : `${r.code} ${r.name}`} <BudgetState state={r.state} /></td>
                    {r.history.map((c: any, i: number) => <td key={i}>{!c && r.history_note ? <i className="muted">history on parent</i> : <Cmp c={c} />}</td>)}
                    <td><Cmp c={r.current} word="YTD" /></td>
                    {data.projected ? <td><Proj p={r.projection} /></td> : null}
                    {data.include_next ? <td><Next n={r.next} /></td> : null}
                  </tr>
                ))}
              </Fragment>
            ) : null)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** #261: Fiscal Year screen - print the planning sheet for the budget meeting. */
export function PlanningSheetDialog({ fy, onClose }: { fy: any; onClose: () => void }) {
  const [asOf, setAsOf] = useState(today());
  const href = (download: boolean) => `/api/reports/planning-sheet${qs({ fiscal_year_id: fy.id, as_of: asOf || null, download: download || null })}`;
  return (
    <Modal title="Fiscal Year Planning Sheet" onClose={onClose} wide>
      <p>A printed form for the budget planning meeting: this year's budgets with what was budgeted, the actual year-to-date and the projection, and blank columns to write in the proposed amounts, with room for new budgets. If a Draft next Fiscal Year exists, its name and dates and the draft amounts are filled in.</p>
      <p className="hint">The filled-in sheet can be scanned and attached to the new Fiscal Year as an Other document. It isn't required for the Fiscal Year closure review.</p>
      <Field label="Actuals as of"><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
      <ProjectionChoices fyId={fy.id} />
      <div className="actions">
        <button onClick={onClose}>Done</button>
        <a className="button" href={href(true)}>Download PDF</a>
        <a className="button primary" href={href(false)} target="_blank" rel="noopener">Open planning sheet PDF</a>
      </div>
    </Modal>
  );
}
