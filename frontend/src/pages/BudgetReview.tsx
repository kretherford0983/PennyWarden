// 2.1.0 (#257) Budget Review report (named Budget Prep until #283) and (#261) the Fiscal Year Planning Sheet -
// Budget Managers only.
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
  const load = () => api.get(`/api/reports/budget-review/projection-choices${qs({ fiscal_year_id: fyId })}`).then((x) => { setD(x); setEdit({}); }, setErr);
  useEffect(() => { setD(null); load(); }, [fyId]);
  if (!d) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const rows = [...d.income.map((x: any) => ({ ...x, sec: "Income" })), ...d.expense.map((x: any) => ({ ...x, sec: "Expense" }))];
  const value = (r: any) => (r.budget_id in edit ? edit[r.budget_id] : r.project);
  const dirty = Object.keys(edit).length > 0;
  const save = async (reset = false) => {
    setBusy(true); setErr(null); setSaved(false);
    try {
      const choices = reset ? [] : Object.entries(edit).map(([id, project]) => ({ budget_id: Number(id), project }));
      setD(await api.put("/api/reports/budget-review/projection-choices", { fiscal_year_id: Number(fyId), choices, reset }));
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

const status = (s: string) => s.charAt(0) + s.slice(1).toLowerCase();

/** #283 (layout A): one column = (Budgeted, Actual, Difference) for a budget. */
type Col = { key: string; head: React.ReactNode; cells: (r: any) => [React.ReactNode, React.ReactNode, React.ReactNode] };

function columns(data: any): Col[] {
  const cols: Col[] = data.years.map((y: any, i: number) => ({
    key: y.entered ? `e${y.year}` : `y${y.id}`,
    head: y.entered ? <>{y.display_name}<div className="muted small">entered</div></> : y.display_name,
    cells: (r: any) => {
      const c = r.history[i];
      if (!c) return [r.history_note ? <i className="muted">history on parent</i> : <span className="muted" title="No linked budget that year">—</span>, null, null];
      // 2.2.0 (#284): a year before PennyWarden, entered from earlier records
      const entered = c.source === "ENTERED" ? (c.from_sub_budgets ? "entered · sum of sub-budgets" : "entered") : null;
      const mismatch = c.mismatch ? `sub-budgets: ${money(c.mismatch.budgeted)} / ${money(c.mismatch.actual)}` : null;
      const note = [entered, mismatch, c.renumbered ? c.code : null, c.entered_as ? `as ${c.entered_as}` : null, c.status && c.status !== "APPROVED" ? status(c.status) : null].filter(Boolean).join(" · ");
      return [<>{money(c.budgeted)}{note ? <div className="muted small">{note}</div> : null}</>, money(c.actual), diffText(c.difference, c.difference_pct)];
    },
  }));
  if (data.years.length) {
    cols.push({ key: "avg", head: <>Avg<div className="muted small">prior years</div></>,
      cells: (r: any) => r.average ? [money(r.average.budgeted), money(r.average.actual), diffText(r.average.difference, r.average.difference_pct)] : [<span className="muted">—</span>, null, null] });
  }
  cols.push({ key: "cur", head: <>{data.fiscal_year.display_name}<div className="muted small">YTD {data.as_of}</div></>,
    cells: (r: any) => [money(r.current.budgeted), money(r.current.actual), diffText(r.current.difference, r.current.difference_pct)] });
  if (data.projected) {
    cols.push({ key: "proj", head: <>Projected<div className="muted small">to {data.fiscal_year.end_date}</div></>,
      cells: (r: any) => {
        const p = r.projection;
        if (!p) return [null, null, null];
        if (p.state === "NOT_PROJECTED") return [money(r.current.budgeted), <i>Complete: no projection</i>, null];
        if (p.state === "TOO_EARLY") return [money(r.current.budgeted), <i>too early to project</i>, null];
        const word = p.state === "ROLLUP" ? "sum of sub-budgets" : p.state === "YEAR_ENDED" ? "year ended: actual" : "projected";
        return [money(r.current.budgeted), <>{money(p.projected)}<div className="muted small">{word}</div></>, diffText(p.difference, p.difference_pct)];
      } });
  }
  if (data.include_next) {
    cols.push({ key: "next", head: <>{data.next_fiscal_year ? data.next_fiscal_year.display_name : "Next year"}<div className="muted small">next year's budget</div></>,
      cells: (r: any) => {
        const n = r.next;
        if (!n) return [<span className="muted">—</span>, null, null];
        const ch = Number(n.change) === 0 ? "no change" : `${n.change.startsWith("-") ? "−" : "+"}${money(n.change.replace("-", ""))} (${pctText(n.change_pct)}) vs this year`;
        return [<>{money(n.amount)}<div className="muted small">{n.code} · {status(n.status)}</div></>, null, ch];
      } });
  }
  return cols;
}

export default function BudgetReview({ fys }: { fys: any[] }) {
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
    api.get(`/api/reports/budget-review/projection-choices${qs({ fiscal_year_id: f.fiscal_year_id })}`).then((d) => setOpts([...d.income, ...d.expense]), () => setOpts([]));
  }, [f.fiscal_year_id]);
  const [kind, id] = f.budget ? f.budget.split(":") : ["", ""];
  const params = (format: string, download = false) => ({
    fiscal_year_id: f.fiscal_year_id, years: f.years, projected: f.projected || null, include_next: f.include_next || null,
    budget_id: kind === "b" ? id : null, parent_budget_id: kind === "p" ? id : null, as_of: f.as_of || null,
    format: format === "json" ? null : format, download: download || null,
  });
  const url = (format: string, download = false) => `/api/reports/budget-review${qs(params(format, download))}`;
  const run = async () => {
    setBusy(true); setErr(null);
    try { setData(await api.get(url("json"))); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <section className="card">
      <h2 className="no-print">Budget Review</h2>
      <p className="no-print">Each budget of the Fiscal Year with its history over earlier years (following the budget continuation links, so a renumbered budget stays on one line), budgeted against actual, the year-to-date actual and, optionally, a projection to the year end and next year's continuing budget. For Budget Managers.</p>
      <div className="report-options no-print">
        <Field label="Fiscal Year">
          <select aria-label="Budget Review Fiscal Year" value={f.fiscal_year_id} onChange={(e) => setF({ ...f, fiscal_year_id: e.target.value, budget: "" })}>
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
      {data ? <BudgetReviewTable data={data} url={url} /> : null}
    </section>
  );
}

function BudgetReviewTable({ data, url }: { data: any; url: (format: string, download?: boolean) => string }) {
  const cols = columns(data);
  const span = cols.length + 1;
  return (
    <div className="budget-review">
      <h2>Budget Review — {data.fiscal_year.display_name}</h2>
      <p>Actuals year-to-date as of {data.as_of}. Prior years shown: {data.years.length} of {data.available_years}. Difference = actual − budgeted; n/a when nothing was budgeted. Avg = the average of the prior years shown in which the budget existed.{data.entered_years ? " Years marked entered are before PennyWarden, entered by a Budget Manager from earlier records." : ""}{data.projected ? ` Projected = YTD ÷ elapsed months × months in the year (${data.projection_basis.elapsed_months} of ${data.projection_basis.months} months elapsed).` : ""}</p>
      <div className="actions left no-print">
        <a className="button primary" href={url("pdf")} target="_blank" rel="noopener">Open PDF</a>
        <a className="button" href={url("pdf", true)}>Download PDF</a>
        <a className="button" href={url("csv")}>Download CSV</a>
      </div>
      <div className="table-scroll">
        <table className="table compact" aria-label="Budget Review">
          <thead><tr><th />{cols.map((c) => <th key={c.key} className="num">{c.head}</th>)}</tr></thead>
          {(["income", "expense"] as const).map((sec) => data[sec].length ? (
            <tbody key={sec}>
              <tr className="section-row"><th colSpan={span}>{sec === "income" ? "Income" : "Expense"}</th></tr>
              {data[sec].map((r: any) => {
                const vals = cols.map((c) => c.cells(r));
                return (
                  <Fragment key={r.id}>
                    <tr className={r.level === "parent" ? "budget-head parent-row" : "budget-head"}>
                      <th colSpan={span} scope="rowgroup" className={r.level === "sub" ? "indent" : ""}>
                        {r.level === "parent" ? <b>{r.code} {r.name}</b> : `${r.code} ${r.name}`} <BudgetState state={r.state} />
                      </th>
                    </tr>
                    {(["Budgeted", "Actual", "Difference"] as const).map((word, k) => (
                      <tr key={word} className={k === 2 ? "last-of-budget" : ""}>
                        <th scope="row" className="muted">{word}</th>
                        {vals.map((v, i) => <td key={cols[i].key} className="num">{v[k]}</td>)}
                      </tr>
                    ))}
                  </Fragment>
                );
              })}
            </tbody>
          ) : null)}
        </table>
      </div>
    </div>
  );
}

/** #261: the planning sheet for the budget meeting, from the Fiscal Years page (build 3 feedback, 2026-10-20). It
 * works out which year is being planned: a Draft year and the year before it (draft amounts fill Proposed, with a
 * Proposed Revision column), otherwise the current year with a blank Proposed column. */
export function PlanningSheetDialog({ onClose }: { onClose: () => void }) {
  const [asOf, setAsOf] = useState(today());
  const [withReview, setWithReview] = useState(false);     // #283: the Budget Review pages after the sheet
  const [c, setC] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/reports/planning-sheet/context").then(setC, setErr); }, []);
  const href = (download: boolean) => `/api/reports/planning-sheet${qs({ as_of: asOf || null, download: download || null, include_review: withReview || null })}`;
  return (
    <Modal title="Fiscal Year Planning Sheet" onClose={onClose} wide>
      <p>A printed form for the budget planning meeting: this year's budgets with what was budgeted, the actual year-to-date and the projection, and blank columns to write in the proposed amounts, with room for new budgets.</p>
      <ErrorBox error={err} />
      {c ? (
        <div className="alert info" role="note" data-testid="planning-context">
          {c.draft_fiscal_year
            ? <>Planning <b>{c.draft_fiscal_year.display_name}</b> (Draft) from <b>{c.fiscal_year.display_name}</b>: the draft's name, dates and amounts are filled in, with a blank <i>Proposed Revision</i> column.</>
            : <>Planning the year after <b>{c.fiscal_year.display_name}</b>: no Draft Fiscal Year yet, so the new year's name, dates and the <i>Proposed Budget</i> column are left blank to fill in.</>}
        </div>
      ) : null}
      <p className="hint">The filled-in sheet can be scanned and attached to the new Fiscal Year as an Other document. It isn't required for the Fiscal Year closure review.</p>
      <Field label="Actuals as of"><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
      <label className="check"><input type="checkbox" checked={withReview} onChange={(e) => setWithReview(e.target.checked)} /> Include the Budget Review <span className="muted">(the last 3 years of each budget — budgeted, actual and difference — after the sheet, in the same PDF)</span></label>
      {c ? <ProjectionChoices fyId={c.fiscal_year.id} /> : null}
      <div className="actions">
        <button onClick={onClose}>Done</button>
        <a className="button" href={href(true)}>Download PDF</a>
        <a className="button primary" href={href(false)} target="_blank" rel="noopener">Open planning sheet PDF</a>
      </div>
    </Modal>
  );
}
