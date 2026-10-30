// 2.1.0 (#277): Fundraiser series (Budget Managers) - the same event across years. Series are created when a
// fundraiser continues an earlier one; here they are renamed, grouped as Other, given results of years before
// PennyWarden (labelled Entered; retired, never deleted) and merged when one event was started twice.
// #292: a series can also be started on a single fundraiser ("Start a series…" here, or "Enter prior years…" on the
// fundraiser), for events whose earlier years all predate PennyWarden; ?enter=<series id> opens its prior-year entry.
// 2.2.0 (#302): "Start a series…" can also add a fundraiser to an existing series (an event held twice a year, in
// its first year in PennyWarden). #351: each table is one list by year, newest first unless the user flipped it
// (Year heading; remembered per user, one choice for every table); the server returns it in order.
import { useEffect, useState } from "react";
import { api, money } from "../api";
import { useMe } from "../App";
import { ErrorBox, Field, Loading, Modal } from "../components";
import { Link, useRouter } from "../router";

const DEFAULT_DIR = "desc";

export default function FundraiserSeries() {
  const [list, setList] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [entering, setEntering] = useState<any>(null);
  const [correcting, setCorrecting] = useState<{ s: any; r: any } | null>(null);   // 2.3.0 (#390)
  const [merging, setMerging] = useState<any>(null);
  const [renaming, setRenaming] = useState<any>(null);
  const [starting, setStarting] = useState(false);
  const { me, patchMe } = useMe();
  const [dir, setDir] = useState<"asc" | "desc">(me.fundraiser_series_sort === "asc" ? "asc" : DEFAULT_DIR);
  const { search } = useRouter();
  const run = async (fn: () => Promise<any>) => { setErr(null); try { setList(await fn()); } catch (x) { setErr(x); } };
  const chooseDir = (next: "asc" | "desc") => {
    setDir(next);
    patchMe({ fundraiser_series_sort: next });
    api.put("/api/me/preferences", { fundraiser_series_sort: next }).catch(() => undefined);
    run(() => api.get(`/api/fundraiser-series?direction=${next}`));
  };
  useEffect(() => {
    api.get(`/api/fundraiser-series?direction=${dir}`).then((l: any[]) => {
      setList(l);
      const want = Number(new URLSearchParams(search).get("enter"));
      const s = want ? l.find((x) => x.id === want) : null;
      if (s) { setEntering(s); setTimeout(() => document.getElementById(`series-${s.id}`)?.scrollIntoView(), 0); }
    }, setErr);
  }, []);
  if (!list) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  return (
    <div>
      <p><Link to="/fundraisers">← Fundraisers</Link></p>
      <div className="page-head"><h1>Fundraiser series</h1><button onClick={() => setStarting(true)}>Start a series…</button></div>
      <p className="hint">A series is the same event across years. It is created when a fundraiser <b>continues from</b> an earlier one (set on the fundraiser), or here with <b>Start a series…</b> when the event's earlier years are all from before PennyWarden. Results of years before PennyWarden are entered on a series with <b>Enter a prior year…</b>; they show as <i>Entered</i> in the Fiscal Year fundraising report and in year over year.</p>
      <p className="hint" data-testid="series-twice-hint"><b>An event held more than once a year</b> (for example a spring and a fall breakfast): “Continues from” links only to an earlier Fiscal Year, so in the event's first year in PennyWarden use <b>Start a series…</b> on one of them, then <b>Start a series…</b> → <i>Add to an existing series</i> for the other. Both count in the same year.</p>
      <ErrorBox error={err} />
      {dir !== DEFAULT_DIR && list.length ? (
        <p className="muted sort-note">Sorted by year, oldest first.{" "}
          <button type="button" className="link" onClick={() => chooseDir(DEFAULT_DIR)}>Reset to default</button></p>
      ) : null}
      {list.length === 0 ? <p className="muted">No series yet. To enter years from before PennyWarden, use <b>Start a series…</b> and choose the fundraiser, or link a fundraiser to an earlier one with “Continues from”.</p> : null}
      {list.map((s) => (
        <section className="card" key={s.id} aria-labelledby={`series-${s.id}`}>
          <div className="charts-head">
            <h2 id={`series-${s.id}`}>{s.name}{s.group_as_other ? <span className="pill"> Grouped as Other</span> : null}</h2>
            <div className="row">
              <button className="small" onClick={() => setRenaming(s)}>Rename…</button>
              <button className="small" onClick={() => run(() => api.patch(`/api/fundraiser-series/${s.id}`, { group_as_other: !s.group_as_other }))}>
                {s.group_as_other ? "Show on its own" : "Group as Other"}</button>
              <button className="small" onClick={() => setEntering(s)}>Enter a prior year…</button>
              {list.length > 1 ? <button className="small" onClick={() => setMerging(s)}>Merge into…</button> : null}
            </div>
          </div>
          <table className="table compact">
            <thead><tr><th aria-sort={dir === "asc" ? "ascending" : "descending"}>
              <button type="button" className="sort-head" onClick={() => chooseDir(dir === "asc" ? "desc" : "asc")}
                title={`Sort by year, ${dir === "asc" ? "newest" : "oldest"} first`}>Year<span aria-hidden="true" className="sort-arrow">{dir === "asc" ? " ▲" : " ▼"}</span></button>
            </th><th>Fundraiser / entry</th><th>Source</th><th className="num">Net raised</th><th>Note</th><th /></tr></thead>
            <tbody>
              {s.rows.map((r: any) => r.kind === "recorded" ? (
                <tr key={`f${r.id}`}><td>{r.year}</td><td><Link to={`/fundraisers/${r.id}`}>{r.name}</Link></td><td>Recorded</td><td className="num muted">on its page</td><td /><td /></tr>
              ) : (
                <tr key={`r${r.id}`} className={r.retired ? "muted" : ""}>
                  <td>{r.year}</td><td>{r.fiscal_year_label}{r.estimated ? <span title="Estimated" data-testid="estimated-mark">*</span> : null}</td><td>{r.retired ? <s>Entered</s> : "Entered"}{r.estimated ? " · estimated" : ""}{r.retired ? ` (retired: ${r.retire_reason})` : ""}</td>
                  <td className="num">{money(r.net)}</td><td>{r.note || ""}</td>
                  <td>{r.retired ? null : <div className="row">
                    {/* 2.3.0 (#390): Correct (reason required) - amounts, note, Estimated */}
                    <button className="small" onClick={() => setCorrecting({ s, r })}>Correct…</button>
                    <button className="small" onClick={() => { const reason = window.prompt("Reason for retiring this entered result"); if (reason) run(() => api.post(`/api/fundraiser-series/${s.id}/results/${r.id}/retire`, { reason })); }}>Retire…</button>
                  </div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {entering ? <EnterResult s={entering} onClose={() => setEntering(null)} onSaved={(x) => { setList(x); setEntering(null); }} /> : null}
      {correcting ? <EnterResult s={correcting.s} result={correcting.r} onClose={() => setCorrecting(null)} onSaved={(x) => { setList(x); setCorrecting(null); }} /> : null}
      {renaming ? <Rename s={renaming} onClose={() => setRenaming(null)} onSaved={(x) => { setList(x); setRenaming(null); }} /> : null}
      {starting ? <StartSeries hasSeries={list.length > 0} onClose={() => setStarting(false)} onSaved={(r, added) => { setStarting(false); setList(r.series); const s = r.series.find((x: any) => x.id === r.series_id); if (s && !added) setEntering(s); }} /> : null}
      {merging ? <Merge s={merging} list={list} onClose={() => setMerging(null)} onSaved={(x) => { setList(x); setMerging(null); }} /> : null}
    </div>
  );
}

/** Enter a prior year, or (2.3.0, #390) Correct an entered one: amounts, note and the Estimated box, reason required. */
function EnterResult({ s, result, onClose, onSaved }: { s: any; result?: any; onClose: () => void; onSaved: (x: any) => void }) {
  const [v, setV] = useState({ fiscal_year_label: result?.fiscal_year_label || "", net: result?.net || "", income: result?.income || "",
    expense: result?.expense || "", note: result?.note || "", estimated: !!result?.estimated, reason: "" });
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setErr(null);
    const body = { net: v.net, income: v.income || null, expense: v.expense || null, note: v.note || null, estimated: v.estimated };
    try {
      onSaved(result
        ? await api.post(`/api/fundraiser-series/${s.id}/results/${result.id}/correct`, { ...body, reason: v.reason })
        : await api.post(`/api/fundraiser-series/${s.id}/results`, { ...body, fiscal_year_label: v.fiscal_year_label }));
    } catch (x) { setErr(x); }
  };
  const set = (k: string) => (e: any) => setV({ ...v, [k]: e.target.value });
  const noteMissing = v.estimated && !v.note.trim();
  return (
    <Modal title={result ? `Correct ${result.fiscal_year_label} — ${s.name}` : `Enter a prior year — ${s.name}`} onClose={onClose}>
      <ErrorBox error={err} />
      {result ? null : <p className="hint">For a year before PennyWarden. A year in which this series already has a fundraiser in PennyWarden is refused, so nothing is counted twice.</p>}
      <div className="row fields">
        {result ? null : <Field label="Fiscal Year (include the year)"><input required maxLength={40} placeholder="FY2019" value={v.fiscal_year_label} onChange={set("fiscal_year_label")} /></Field>}
        <Field label="Amount raised (net)"><input required inputMode="decimal" value={v.net} onChange={set("net")} /></Field>
      </div>
      <div className="row fields">
        <Field label="Income (optional)"><input inputMode="decimal" value={v.income} onChange={set("income")} /></Field>
        <Field label="Expenses (optional)"><input inputMode="decimal" value={v.expense} onChange={set("expense")} /></Field>
      </div>
      <label className="check"><input type="checkbox" checked={v.estimated} onChange={(e) => setV({ ...v, estimated: e.target.checked })} /> Estimated</label>
      <Field label={v.estimated ? "Note (required: why it is estimated)" : "Note (optional)"} hint={v.estimated ? "Printed as the footnote wherever the year is marked *." : undefined}>
        <input maxLength={500} placeholder="e.g. bundled with another event" value={v.note} onChange={set("note")} /></Field>
      {result ? <Field label="Reason for the correction (required)"><input maxLength={500} value={v.reason} onChange={set("reason")} /></Field> : null}
      <div className="actions"><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={(!result && !v.fiscal_year_label) || !v.net || noteMissing || (!!result && !v.reason.trim())} onClick={save}>Save</button></div>
    </Modal>
  );
}

function Rename({ s, onClose, onSaved }: { s: any; onClose: () => void; onSaved: (x: any) => void }) {
  const [name, setName] = useState(s.name);
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal title="Rename series" onClose={onClose}>
      <ErrorBox error={err} />
      <Field label="Series name"><input maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <div className="actions"><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={!name.trim()} onClick={async () => { try { onSaved(await api.patch(`/api/fundraiser-series/${s.id}`, { name })); } catch (x) { setErr(x); } }}>Save</button></div>
    </Modal>
  );
}

function Merge({ s, list, onClose, onSaved }: { s: any; list: any[]; onClose: () => void; onSaved: (x: any) => void }) {
  const others = list.filter((x) => x.id !== s.id);
  const [into, setInto] = useState(others[0] ? String(others[0].id) : "");
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal title={`Merge ${s.name}`} onClose={onClose}>
      <ErrorBox error={err} />
      <p>Moves the fundraisers and entered results of <b>{s.name}</b> into the series you choose. Refused when both have an entered result for the same year — retire one first.</p>
      <Field label="Merge into">
        <select value={into} onChange={(e) => setInto(e.target.value)}>{others.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
      </Field>
      <div className="actions"><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={!into} onClick={async () => { try { onSaved(await api.post(`/api/fundraiser-series/${s.id}/merge`, { into_series_id: Number(into) })); } catch (x) { setErr(x); } }}>Merge</button></div>
    </Modal>
  );
}

function StartSeries({ hasSeries, onClose, onSaved }: { hasSeries: boolean; onClose: () => void; onSaved: (x: any, added: boolean) => void }) {
  const [opts, setOpts] = useState<any[] | null>(null);
  const [pick, setPick] = useState("");
  const [mode, setMode] = useState<"new" | "add">("new");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/fundraiser-series/start-options").then((l: any[]) => { setOpts(l); if (l.length) setPick(String(l[0].id)); }, setErr); }, []);
  const chosen = opts?.find((o) => String(o.id) === pick);
  const [into, setInto] = useState("");
  const save = async () => {
    setErr(null);
    try {
      onSaved(mode === "add" ? await api.put(`/api/fundraisers/${pick}/series`, { series_id: Number(into) })
        : await api.post(`/api/fundraisers/${pick}/series`), mode === "add");
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Start a series" onClose={onClose}>
      <ErrorBox error={err} />
      {!opts ? (err ? null : <Loading />) : opts.length === 0 ? <p className="muted">Every fundraiser is already in a series.</p> : <>
        <Field label="Fundraiser">
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            {opts.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.year})</option>)}
          </select>
        </Field>
        <fieldset className="choices">
          <legend className="sr-only">Series</legend>
          <label className="check"><input type="radio" name="start-mode" checked={mode === "new"} onChange={() => setMode("new")} /> Start a new series</label>
          <label className="check"><input type="radio" name="start-mode" checked={mode === "add"} disabled={!hasSeries} onChange={() => setMode("add")} /> Add to an existing series{hasSeries ? "" : <span className="muted"> (no series yet)</span>}</label>
        </fieldset>
        {mode === "new" ? <>
          <p className="hint">For a fundraiser whose earlier years are from before PennyWarden: a series is created for it so those years can be entered.</p>
          {chosen ? <p className="hint">The series will be named <b>{chosen.series_name}</b>; it can be renamed later.</p> : null}
        </> : pick ? <AddChoice fid={pick} into={into} setInto={setInto} /> : null}
      </>}
      <div className="actions"><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={!pick || (mode === "add" && !into)} onClick={save}>{mode === "add" ? "Add to series" : "Start series"}</button></div>
    </Modal>
  );
}

/** 2.2.0 (#302): the series a fundraiser can join; one with an entered result for its year is shown but disabled. */
export function AddChoice({ fid, into, setInto }: { fid: string | number; into: string; setInto: (v: string) => void }) {
  const [opts, setOpts] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    setOpts(null);
    api.get(`/api/fundraisers/${fid}/series-add-options`).then((l: any[]) => {
      setOpts(l);
      const first = l.find((o) => o.allowed);
      setInto(first ? String(first.id) : "");
    }, setErr);
  }, [fid]);
  if (!opts) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  if (!opts.length) return <p className="muted">No series yet.</p>;
  return <>
    <Field label="Series">
      <select value={into} onChange={(e) => setInto(e.target.value)}>
        {opts.map((o) => <option key={o.id} value={o.id} disabled={!o.allowed}>{o.name}{o.allowed ? "" : ` — not available: ${o.reason}`}</option>)}
      </select>
    </Field>
    <p className="hint">For an event held more than once a year: both fundraisers count in the same year of the series. “Continues from” stays empty. A series that has an entered result for this fundraiser's year can't be chosen, so the year is not counted twice.</p>
  </>;
}
