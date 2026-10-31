// 2.1.0 (#257) Budget Review report (named Budget Prep until #283) and (#261) the Fiscal Year Planning Sheet -
// Budget Managers only.
// Both use the same projection rule and the same per-user, per-budget projection choices.
import { Fragment, useEffect, useState } from "react";
import { api, money, qs } from "../api";
import { BudgetState, ErrorBox, Field, GrossBudgetNote, Loading } from "../components";
import type { ActionsFn, RunFn } from "./reports/common";

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

/** 2.3.0 polish: added columns (prior years + Projected + Next year's budget) the PDF fits on one landscape page;
 * the same numbers as budget_planning.pdf_max_added. */
const PAPER_MAX: Record<string, number> = { LETTER: 6, LEGAL: 9 };

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
      // 2.2.0: "history on parent" only in years the parent held one amount of its own (else the sub-budget had none);
      // 2.3.0 (#414): or "included in …" where a Budget Manager marked the year on the budget's History
      const hn: string | null | undefined = r.history_notes?.[i];
      if (!c) return [hn ? <i className="muted" title={hn === "history on parent" ? "The parent had no sub-budgets that year: its amount includes this one" : "Its money was included in another budget that year (marked on its History); not counted in Avg"}>{hn}</i> : <span className="muted" title="No linked budget that year">—</span>, null, null];
      // 2.2.0 (#284): a year before PennyWarden, entered from earlier records
      const entered = c.source === "ENTERED" ? (c.from_sub_budgets ? "entered · sum of sub-budgets" : "entered") : null;
      const mismatch = c.mismatch ? `sub-budgets: ${money(c.mismatch.budgeted)} / ${money(c.mismatch.actual)}` : null;
      const note = [entered, mismatch, c.renumbered ? c.code : null, c.entered_as ? `as ${c.entered_as}` : null, c.status && c.status !== "APPROVED" ? status(c.status) : null].filter(Boolean).join(" · ");
      // 2.3.0 (#390): an estimated year is marked * (the footnote under the table gives the note)
      const star = c.estimated ? <span title={`Estimated: ${c.estimate_note || ""}`}>*</span> : null;
      return [<>{money(c.budgeted)}{star}{note ? <div className="muted small">{note}</div> : null}</>, <>{money(c.actual)}{star}</>, diffText(c.difference, c.difference_pct)];
    },
  }));
  if (data.years.length) {
    cols.push({ key: "avg", head: <>Avg<div className="muted small">prior years</div></>,
      cells: (r: any) => r.average ? [money(r.average.budgeted), money(r.average.actual), diffText(r.average.difference, r.average.difference_pct)] : [<span className="muted">—</span>, null, null] });
  }
  cols.push({ key: "cur", head: <>{data.fiscal_year.display_name}<div className="muted small">YTD {data.as_of}</div></>,
    cells: (r: any) => !r.current ? [<span className="muted" title={`No budget in ${data.fiscal_year.display_name}`}>—</span>, null, null]   // 2.3.0 (#382)
      : [money(r.current.budgeted), money(r.current.actual), diffText(r.current.difference, r.current.difference_pct)] });
  if (data.projected) {
    cols.push({ key: "proj", head: <>Projected<div className="muted small">to {data.fiscal_year.end_date}</div></>,
      cells: (r: any) => {
        const p = r.projection;
        if (!p) return [r.current ? null : <span className="muted">—</span>, null, null];
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

export default function BudgetReview({ fys, initial = {}, onRun }: { fys: any[]; initial?: Record<string, any>; onRun?: RunFn }) {
  const t = today();
  const cur = fys.find((f) => f.start_date <= t && f.end_date >= t) || fys[fys.length - 1];
  // 2.3.0 (#375): the user's last Fiscal Year, prior years and budgets are filled in; the optional columns and as-of
  // start as usual
  // 2.3.0 polish (Kyle, 2026-10-31): the PDF keeps every column on one page - prior years + Projected + Next year's
  // budget add up to 6 columns on letter, 9 on legal (landscape); the Prior years list follows the paper chosen
  const startPaper = initial.paper === "LEGAL" ? "LEGAL" : "LETTER";
  const [f, setF] = useState({ fiscal_year_id: String(initial.fiscal_year_id || (cur ? cur.id : "")),
    // a saved "All linked years" (before 2.3.0 polish) becomes the most that fits; others are capped to it
    years: String(Number(initial.years ?? 3) < 0 || Number.isNaN(Number(initial.years ?? 3)) ? PAPER_MAX[startPaper] : Math.min(Number(initial.years ?? 3), PAPER_MAX[startPaper])),
    projected: false, include_next: false, budget: String(initial.budget || ""), as_of: t, paper: startPaper });
  const extras = (f.projected ? 1 : 0) + (f.include_next ? 1 : 0);
  const maxYears = PAPER_MAX[f.paper] - extras;
  /** a change of paper or columns: prior years come down to what still fits */
  const upd = (patch: Partial<typeof f>) => setF((x) => {
    const n = { ...x, ...patch };
    const cap = PAPER_MAX[n.paper] - (n.projected ? 1 : 0) - (n.include_next ? 1 : 0);
    return Number(n.years) > cap ? { ...n, years: String(cap) } : n;
  });
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
    paper: format === "pdf" && f.paper !== "LETTER" ? f.paper : null,
  });
  const url = (format: string, download = false) => `/api/reports/budget-review${qs(params(format, download))}`;
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      setData(await api.get(url("json")));
      const y = fys.find((x) => String(x.id) === f.fiscal_year_id);
      onRun?.({ fiscal_year_id: f.fiscal_year_id, years: f.years, budget: f.budget, paper: f.paper },
        `${y?.display_name || ""} · ${f.years === "-1" ? "all" : f.years} prior year${f.years === "1" ? "" : "s"}`);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <>
      <p className="no-print">Each budget of the Fiscal Year with its history over earlier years (following the budget continuation links, so a renumbered budget stays on one line) — and the budgets of those years that are not in this Fiscal Year, marked <i>Not in</i> — budgeted against actual, the year-to-date actual and, optionally, a projection to the year end and next year's continuing budget.</p>
      <div className="report-options no-print">
        <Field label="Fiscal Year">
          <select aria-label="Budget Review Fiscal Year" value={f.fiscal_year_id} onChange={(e) => setF({ ...f, fiscal_year_id: e.target.value, budget: "" })}>
            {fys.map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
          </select>
        </Field>
        <Field label="Paper (PDF)">
          <select aria-label="PDF paper" value={f.paper} onChange={(e) => upd({ paper: e.target.value })}>
            <option value="LETTER">Letter, landscape</option>
            <option value="LEGAL">Legal, landscape</option>
          </select>
        </Field>
        <Field label="Prior years">
          <select aria-label="Prior years" value={f.years} onChange={(e) => upd({ years: e.target.value })}>
            {Array.from({ length: maxYears + 1 }, (_x, n) => <option key={n} value={n}>{n}</option>)}
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
        <label className="check"><input type="checkbox" checked={f.projected} onChange={(e) => upd({ projected: e.target.checked })} /> Projected column</label>
        <label className="check"><input type="checkbox" checked={f.include_next} onChange={(e) => upd({ include_next: e.target.checked })} /> Next year's budget</label>
        <button className="primary" onClick={run} disabled={!f.fiscal_year_id || busy}>{busy ? "Running…" : "Run report"}</button>
      </div>
      <p className="hint no-print" data-testid="review-columns-hint">Prior years, Projected and Next year's budget add up to {PAPER_MAX[f.paper]} columns on
        {f.paper === "LEGAL" ? " legal" : " letter"} paper, so every column of the PDF stays on one page{f.paper === "LETTER" ? ` (legal fits ${PAPER_MAX.LEGAL})` : ""}.</p>
      {f.projected && f.fiscal_year_id ? <ProjectionChoices fyId={f.fiscal_year_id} onSaved={() => data && run()} /> : null}
      <ErrorBox error={err} />
      {data ? <BudgetReviewTable data={data} url={url} paper={f.paper} /> : null}
    </>
  );
}

function BudgetReviewTable({ data, url, paper }: { data: any; url: (format: string, download?: boolean) => string; paper: string }) {
  const cols = columns(data);
  // 2.3.0 polish: the PDF keeps every column on one page (the options keep a run within it; this guards a paper
  // changed after running)
  const limits = data.pdf_max_added || PAPER_MAX;
  const fits = data.added_columns <= limits[paper];
  // 2.3.0 (#390): one footnote line per estimated year
  const estimates: any[] = [];
  for (const sec of ["income", "expense"]) for (const r of data[sec]) r.history.forEach((c: any, i: number) => {
    if (c?.estimated) estimates.push({ label: data.years[i].display_name, code: r.code, name: r.name, note: c.estimate_note });
  });
  const span = cols.length + 1;
  return (
    <div className="budget-review">
      <h2>Budget Review — {data.fiscal_year.display_name}</h2>
      <p>Actuals year-to-date as of {data.as_of}. Prior years shown: {data.years.length} of {data.available_years}. Difference = actual − budgeted; n/a when nothing was budgeted. Avg = the average of the prior years shown in which the budget existed.{data.entered_years ? " Years marked entered are before PennyWarden, entered by a Budget Manager from earlier records." : ""}{data.projected ? ` Projected = YTD ÷ elapsed months × months in the year (${data.projection_basis.elapsed_months} of ${data.projection_basis.months} months elapsed).` : ""}</p>
      <div className="actions left no-print">
        {fits ? <>
          <a className="button primary" href={url("pdf")} target="_blank" rel="noopener">Open PDF</a>
          <a className="button" href={url("pdf", true)}>Download PDF</a>
        </> : <>
          <button className="primary" disabled>Open PDF</button>
          <button disabled>Download PDF</button>
        </>}
        <a className="button" href={url("csv")}>Download CSV</a>
      </div>
      {!fits ? <div className="alert warn no-print" role="status" data-testid="review-pdf-limit">This report has {data.added_columns} added
        columns (prior years, Projected and Next year's budget); the PDF fits {limits[paper]} on {paper === "LEGAL" ? "legal" : "letter"} paper so
        every column stays on one page. Run it again with fewer prior years or columns{paper === "LETTER" && data.added_columns <= limits.LEGAL ? ", or choose legal paper" : ""}.</div> : null}
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
                        {r.level === "parent" ? <b>{r.code} {r.name}</b> : `${r.code} ${r.name}`} {r.state ? <BudgetState state={r.state} /> : null}
                        {/* 2.3.0 (#382): a budget of the years shown that has no budget in the chosen Fiscal Year */}
                        {r.not_in_year ? <span className="badge grey" data-testid="not-in-year">Not in {r.not_in_year.fiscal_year}, last {r.not_in_year.last_year}</span> : null}
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
      {estimates.length ? (
        <ul className="hint estimate-notes" data-testid="estimate-notes">
          {estimates.map((e, i) => <li key={i}>* Estimated: {e.label} {e.code} {e.name} — {e.note}</li>)}
        </ul>
      ) : null}
      <GrossBudgetNote />
    </div>
  );
}

/** #261: the planning sheet for the budget meeting. It works out which year is being planned: a Draft year and the
 * year before it (draft amounts fill Proposed, with a Proposed Revision column), otherwise the current year with a
 * blank Proposed column. 2.3.0 (#375): a report page in Reports; the Fiscal Years page's button is a shortcut to it. */
export function PlanningSheetReport({ initial, onRun, actions }: { initial: Record<string, any>; onRun: RunFn; actions: ActionsFn }) {
  const [asOf, setAsOf] = useState(today());
  const [withReview, setWithReview] = useState(initial.include_review === true);     // #283: the Budget Review pages after the sheet
  const [c, setC] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/reports/planning-sheet/context").then(setC, setErr); }, []);
  const href = (download: boolean) => `/api/reports/planning-sheet${qs({ as_of: asOf || null, download: download || null, include_review: withReview || null })}`;
  return (
    <>
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
      {actions({ open: href(false), download: href(true), onRun: () => onRun({ include_review: withReview }, c ? `Planning from ${c.fiscal_year.display_name}` : "") })}
    </>
  );
}
