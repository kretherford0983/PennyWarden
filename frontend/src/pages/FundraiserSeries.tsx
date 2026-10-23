// 2.1.0 (#277): Fundraiser series (Budget Managers) - the same event across years. Series are created when a
// fundraiser continues an earlier one; here they are renamed, grouped as Other, given results of years before
// PennyWarden (labelled Entered; retired, never deleted) and merged when one event was started twice.
// #292: a series can also be started on a single fundraiser ("Start a series…" here, or "Enter prior years…" on the
// fundraiser), for events whose earlier years all predate PennyWarden; ?enter=<series id> opens its prior-year entry.
import { useEffect, useState } from "react";
import { api, money } from "../api";
import { ErrorBox, Field, Loading, Modal } from "../components";
import { Link, useRouter } from "../router";

export default function FundraiserSeries() {
  const [list, setList] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [entering, setEntering] = useState<any>(null);
  const [merging, setMerging] = useState<any>(null);
  const [renaming, setRenaming] = useState<any>(null);
  const [starting, setStarting] = useState(false);
  const { search } = useRouter();
  const run = async (fn: () => Promise<any>) => { setErr(null); try { setList(await fn()); } catch (x) { setErr(x); } };
  useEffect(() => {
    api.get("/api/fundraiser-series").then((l: any[]) => {
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
      <ErrorBox error={err} />
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
            <thead><tr><th>Year</th><th>Fundraiser / entry</th><th>Source</th><th className="num">Net raised</th><th>Note</th><th /></tr></thead>
            <tbody>
              {s.fundraisers.map((f: any) => (
                <tr key={`f${f.id}`}><td>{f.year}</td><td><Link to={`/fundraisers/${f.id}`}>{f.name}</Link></td><td>Recorded</td><td className="num muted">on its page</td><td /><td /></tr>
              ))}
              {s.results.map((r: any) => (
                <tr key={`r${r.id}`} className={r.retired ? "muted" : ""}>
                  <td>{r.year}</td><td>{r.fiscal_year_label}</td><td>{r.retired ? <s>Entered</s> : "Entered"}{r.retired ? ` (retired: ${r.retire_reason})` : ""}</td>
                  <td className="num">{money(r.net)}</td><td>{r.note || ""}</td>
                  <td>{r.retired ? null : <button className="small" onClick={() => { const reason = window.prompt("Reason for retiring this entered result"); if (reason) run(() => api.post(`/api/fundraiser-series/${s.id}/results/${r.id}/retire`, { reason })); }}>Retire…</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {entering ? <EnterResult s={entering} onClose={() => setEntering(null)} onSaved={(x) => { setList(x); setEntering(null); }} /> : null}
      {renaming ? <Rename s={renaming} onClose={() => setRenaming(null)} onSaved={(x) => { setList(x); setRenaming(null); }} /> : null}
      {starting ? <StartSeries onClose={() => setStarting(false)} onSaved={(r) => { setStarting(false); setList(r.series); const s = r.series.find((x: any) => x.id === r.series_id); if (s) setEntering(s); }} /> : null}
      {merging ? <Merge s={merging} list={list} onClose={() => setMerging(null)} onSaved={(x) => { setList(x); setMerging(null); }} /> : null}
    </div>
  );
}

function EnterResult({ s, onClose, onSaved }: { s: any; onClose: () => void; onSaved: (x: any) => void }) {
  const [v, setV] = useState({ fiscal_year_label: "", net: "", income: "", expense: "", note: "" });
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setErr(null);
    try {
      onSaved(await api.post(`/api/fundraiser-series/${s.id}/results`, { fiscal_year_label: v.fiscal_year_label, net: v.net,
        income: v.income || null, expense: v.expense || null, note: v.note || null }));
    } catch (x) { setErr(x); }
  };
  const set = (k: string) => (e: any) => setV({ ...v, [k]: e.target.value });
  return (
    <Modal title={`Enter a prior year — ${s.name}`} onClose={onClose}>
      <ErrorBox error={err} />
      <p className="hint">For a year before PennyWarden. A year in which this series already has a fundraiser in PennyWarden is refused, so nothing is counted twice.</p>
      <div className="row fields">
        <Field label="Fiscal Year (include the year)"><input required maxLength={40} placeholder="FY2019" value={v.fiscal_year_label} onChange={set("fiscal_year_label")} /></Field>
        <Field label="Amount raised (net)"><input required inputMode="decimal" value={v.net} onChange={set("net")} /></Field>
      </div>
      <div className="row fields">
        <Field label="Income (optional)"><input inputMode="decimal" value={v.income} onChange={set("income")} /></Field>
        <Field label="Expenses (optional)"><input inputMode="decimal" value={v.expense} onChange={set("expense")} /></Field>
      </div>
      <Field label="Note (optional)"><input maxLength={500} placeholder="e.g. estimated, bundled with another event" value={v.note} onChange={set("note")} /></Field>
      <div className="actions"><button onClick={onClose}>Cancel</button><button className="primary" disabled={!v.fiscal_year_label || !v.net} onClick={save}>Save</button></div>
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

function StartSeries({ onClose, onSaved }: { onClose: () => void; onSaved: (x: any) => void }) {
  const [opts, setOpts] = useState<any[] | null>(null);
  const [pick, setPick] = useState("");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/fundraiser-series/start-options").then((l: any[]) => { setOpts(l); if (l.length) setPick(String(l[0].id)); }, setErr); }, []);
  const chosen = opts?.find((o) => String(o.id) === pick);
  return (
    <Modal title="Start a series" onClose={onClose}>
      <ErrorBox error={err} />
      {!opts ? (err ? null : <Loading />) : opts.length === 0 ? <p className="muted">Every fundraiser is already in a series.</p> : <>
        <p>Choose the fundraiser whose earlier years are from before PennyWarden. A series is created for it so those years can be entered.</p>
        <Field label="Fundraiser">
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            {opts.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.year})</option>)}
          </select>
        </Field>
        {chosen ? <p className="hint">The series will be named <b>{chosen.series_name}</b>; it can be renamed later.</p> : null}
      </>}
      <div className="actions"><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={!pick} onClick={async () => { setErr(null); try { onSaved(await api.post(`/api/fundraisers/${pick}/series`)); } catch (x) { setErr(x); } }}>Start series</button></div>
    </Modal>
  );
}
