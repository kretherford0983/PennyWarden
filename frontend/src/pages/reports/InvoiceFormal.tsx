/** 2.4.0 (#513): the invoice reports for formal publication - Sales by product & category, and the Sales overview.
 * A Fiscal Year quarter or the year (with the same period last year beside it), or a custom From/Through range (no
 * comparison); a commentary for this run (free text: not remembered); customer names on or off. PDF and presentation.
 * The Fiscal Years come from the invoice options endpoint: an Invoice Manager may not hold the financial permission. */
import { useEffect, useState } from "react";
import { api, qs, todayIso } from "../../api";
import { ErrorBox, Field, Loading } from "../../components";
import type { ActionsFn, RunFn } from "./common";

type Props = { rid: "inv-sales-formal" | "inv-overview"; initial: Record<string, any>; onRun: RunFn; actions: ActionsFn };

export function InvoiceFormalReport({ rid, initial, onRun, actions }: Props) {
  const [kind, setKind] = useState<"FY" | "CUSTOM">(initial.date_from ? "CUSTOM" : "FY");
  const [fy, setFy] = useState(String(initial.fiscal_year_id || ""));
  const [opts, setOpts] = useState<any>(null);
  const [period, setPeriod] = useState("");
  const [from, setFrom] = useState<string>(initial.date_from || "");
  // #528: a custom range remembered "through today" reopens through the day it is opened
  const [through, setThrough] = useState<string>(initial.date_to || (initial.date_from ? todayIso() : ""));
  const [names, setNames] = useState(initial.show_names !== false && initial.show_names !== "false");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    // the first load (no Fiscal Year yet) picks one and sets it: its options are already here, so don't fetch them
    // again - a second answer would reset a period chosen meanwhile
    if (opts && String(opts.fiscal_year_id) === fy) return;
    setErr(null);
    let stale = false;                                  // an answer for a Fiscal Year no longer chosen is dropped
    api.get(`/api/invoices/formal/options${qs({ fiscal_year_id: fy || null })}`).then((o) => {
      if (stale) return;
      setOpts(o);
      if (!fy && o.fiscal_year_id) setFy(String(o.fiscal_year_id));
      const ok = o.periods.filter((p: any) => p.selectable && p.id !== "ANNUAL");
      const wanted = String(initial.fiscal_year_id || "") === String(o.fiscal_year_id) && o.periods.find((p: any) => p.id === initial.period && p.selectable);
      setPeriod(wanted ? wanted.id : ok.length ? ok[ok.length - 1].id : (o.periods.find((p: any) => p.selectable)?.id || ""));
    }, (x) => { if (!stale) setErr(x); });
    return () => { stale = true; };
  }, [fy]);
  if (!opts) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const sel = opts.periods.find((p: any) => p.id === period);
  const rangeOk = !!from && !!through && from <= through;
  const ready = kind === "FY" ? !!sel?.selectable : rangeOk;
  const params = kind === "FY" ? { fiscal_year_id: fy, period } : { date_from: from, date_to: through };
  const remembered = kind === "FY" ? params : { date_from: from, date_to: through === todayIso() ? null : through };
  const url = (format: string, download: boolean) => `/api/invoices/formal/${rid}${qs({ ...params, show_names: names ? null : false,
    commentary: note.trim() || null, format: format === "pdf" ? null : format, download: download || null })}`;
  const fyName = opts.fiscal_years.find((y: any) => String(y.id) === fy)?.label || "";
  const label = kind === "FY" ? `${fyName} · ${period === "ANNUAL" ? "Annual" : period}` : `${from} – ${through}`;
  return (
    <>
      {rid === "inv-sales-formal"
        ? <p>Sales for the board and members: by category, by product within each category, and by Income budget – what was invoiced
          (after discounts, before sales tax), its share, what has been collected so far and, for a Fiscal Year period, the same period
          last year beside it. A PDF report and a presentation with charts.</p>
        : <p>The period's invoicing in one report for the board and members: sales, sales tax, money collected and refunded by month,
          what is open and overdue at the end, discounts and write-offs, the top customers and products, with the same period last year
          beside them. A PDF report and a presentation with charts.</p>}
      <ErrorBox error={err} />
      <fieldset className="report-options">
        <legend>Period</legend>
        <label className="check"><input type="radio" name={`${rid}-kind`} checked={kind === "FY"} onChange={() => setKind("FY")} /> A Fiscal Year quarter or the year</label>
        <label className="check"><input type="radio" name={`${rid}-kind`} checked={kind === "CUSTOM"} onChange={() => setKind("CUSTOM")} /> Dates of my choice</label>
        {kind === "FY" ? (
          <div className="row fields">
            <Field label="Fiscal Year">
              <select aria-label="Sales report Fiscal Year" value={fy} onChange={(e) => setFy(e.target.value)}>
                {opts.fiscal_years.map((y: any) => <option key={y.id} value={y.id}>{y.label}</option>)}
              </select>
            </Field>
            <Field label="Quarter or year">
              <select aria-label="Quarter or year" value={period} onChange={(e) => setPeriod(e.target.value)}>
                {opts.periods.map((p: any) => <option key={p.id} value={p.id} disabled={!p.selectable}>
                  {p.label}{p.id !== "ANNUAL" ? ` (${p.start_date} – ${p.end_date})` : ""}{!p.selectable ? " – not started" : ""}</option>)}
              </select>
            </Field>
          </div>
        ) : (
          <div className="row fields">
            <Field label="From"><input type="date" aria-label="From" value={from} max={opts.today} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="Through"><input type="date" aria-label="Through" value={through} onChange={(e) => setThrough(e.target.value)} /></Field>
          </div>
        )}
      </fieldset>
      {kind === "FY" && sel?.preliminary ? <p className="hint" data-testid="formal-preliminary">{sel.id === "ANNUAL" ? "The Fiscal Year has not ended yet" : "This quarter has not ended yet"}:
        the report is marked <b>Preliminary</b>.</p> : null}
      {kind === "FY" && !opts.prior_fiscal_year ? <p className="hint">No earlier Fiscal Year: there is no comparison with last year.</p> : null}
      {kind === "CUSTOM" ? (from && through && from > through ? <p className="error" role="alert">From must be on or before Through.</p>
        : <p className="hint">Dates of your choice have no comparison with last year. A range that ends after today is reported as of today, marked Preliminary.</p>) : null}
      <label className="check"><input type="checkbox" checked={names} onChange={(e) => setNames(e.target.checked)} /> Show customer names</label>
      {!names ? <p className="hint">Customers are shown as Customer 1, Customer 2, … in the order of their sales.</p> : null}
      <Field label="Commentary (optional)" hint="Printed on the first page of the report and on its own slide in the presentation. Not remembered: write it for each run.">
        <textarea rows={4} maxLength={opts.max_commentary || 2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {actions({ open: ready ? url("pdf", false) : null, download: ready ? url("pdf", true) : null, pptx: ready ? url("pptx", true) : null,
        onRun: () => onRun({ ...remembered, show_names: names }, label) })}
    </>
  );
}
