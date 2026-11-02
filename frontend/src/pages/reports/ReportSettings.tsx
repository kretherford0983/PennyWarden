/** 2.3.0 (#376): System/About -> Report settings (Administrators). How the Reports catalog is grouped for everyone in
 * the organization: the scheme (Purpose, Subject or Audience) and, within it, the categories - add, rename, reorder,
 * remove (its reports go to another category or a new "Other") - and which category each report is in, in what order.
 * Display only: who can run a report doesn't change. */
import { useEffect, useState } from "react";
import { api } from "../../api";
import { ErrorBox, Field, Loading } from "../../components";
import { REPORTS } from "./registry";

type Cat = { id?: string; name: string; short?: string; reports: string[] };
const nameOf = (id: string) => REPORTS.find((r) => r.id === id)?.name || id;
const move = <T,>(xs: T[], i: number, d: number): T[] => {
  const j = i + d;
  if (j < 0 || j >= xs.length) return xs;
  const out = [...xs];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
};

export function ReportSettings() {
  const [v, setV] = useState<any>(null);
  const [scheme, setScheme] = useState("PURPOSE");
  const [cats, setCats] = useState<Cat[]>([]);
  const [newName, setNewName] = useState("");
  const [removing, setRemoving] = useState<{ index: number; target: string } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const take = (d: any, s?: string) => {
    setV(d);
    const sc = s || d.scheme;
    setScheme(sc);
    setCats(d.schemes.find((x: any) => x.id === sc).categories.map((c: Cat) => ({ ...c, reports: [...c.reports] })));
    setDirty(false);
  };
  useEffect(() => { api.get("/api/system/report-settings").then((d) => take(d), setErr); }, []);
  if (!v) return err ? <ErrorBox error={err} /> : <Loading />;
  const edit = (next: Cat[]) => { setCats(next); setDirty(true); setSaved(false); };
  const pick = (s: string) => {
    if (dirty && !window.confirm("Leave this grouping without saving your changes?")) return;
    take(v, s);
    setSaved(false);
  };
  const save = async () => {
    setErr(null); setSaved(false);
    try { take(await api.put("/api/system/report-settings", { scheme, categories: cats }), scheme); setSaved(true); } catch (x) { setErr(x); }
  };
  const reset = async () => {
    if (!window.confirm("Put this grouping back to its defaults?")) return;
    setErr(null); setSaved(false);
    try { take(await api.post("/api/system/report-settings/reset", { scheme }), scheme); setSaved(true); } catch (x) { setErr(x); }
  };
  const add = () => {
    const n = newName.trim();
    if (!n) return;
    edit([...cats, { name: n, reports: [] }]);
    setNewName("");
  };
  const remove = (i: number, target: string) => {
    const moving = cats[i].reports;
    let next = cats.filter((_, j) => j !== i);
    if (moving.length) {
      if (target === "__other") {
        const o = next.findIndex((c) => c.name.toLowerCase() === "other");
        if (o >= 0) next = next.map((c, j) => (j === o ? { ...c, reports: [...c.reports, ...moving] } : c));
        else next = [...next, { name: "Other", reports: moving }];
      } else {
        const t = Number(target);
        const idx = t > i ? t - 1 : t;
        next = next.map((c, j) => (j === idx ? { ...c, reports: [...c.reports, ...moving] } : c));
      }
    }
    edit(next);
    setRemoving(null);
  };
  const moveReport = (from: number, rid: string, to: number) =>
    edit(cats.map((c, j) => (j === from ? { ...c, reports: c.reports.filter((x) => x !== rid) } : j === to ? { ...c, reports: [...c.reports, rid] } : c)));
  const active = v.scheme;
  const current = v.schemes.find((x: any) => x.id === scheme);
  return (
    <section className="card" aria-labelledby="rs-h">
      <h2 id="rs-h">Report settings</h2>
      <p className="hint">How the Reports catalog is grouped for everyone in the organization. Grouping is for finding reports only: who can run a
        report doesn't change, and a category without a report someone can run is hidden from them.</p>
      <ErrorBox error={err} />
      <fieldset className="lines">
        <legend>Group reports by</legend>
        <div className="row" role="radiogroup" aria-label="Group reports by">
          {v.schemes.map((s: any) => (
            <label key={s.id} className="check">
              <input type="radio" name="rs-scheme" checked={scheme === s.id} onChange={() => pick(s.id)} /> {s.label}
              {s.id === active ? <span className="badge">In use</span> : null}{s.customized ? <span className="muted"> (customized)</span> : null}
            </label>
          ))}
        </div>
      </fieldset>
      <ol className="rs-categories" aria-label={`${current.label} categories`}>
        {cats.map((c, i) => (
          <li key={i} className="rs-category" data-testid="rs-category">
            <div className="row form-row">
              <Field label={`Category ${i + 1} name`}>
                <input maxLength={v.max_name} value={c.name} onChange={(e) => edit(cats.map((x, j) => (j === i ? { ...x, name: e.target.value, short: undefined } : x)))} />
              </Field>
              <button type="button" className="small" aria-label={`Move ${c.name} up`} disabled={i === 0} onClick={() => edit(move(cats, i, -1))}>↑</button>
              <button type="button" className="small" aria-label={`Move ${c.name} down`} disabled={i === cats.length - 1} onClick={() => edit(move(cats, i, 1))}>↓</button>
              <button type="button" className="small" disabled={cats.length === 1}
                      onClick={() => (c.reports.length ? setRemoving({ index: i, target: "__other" }) : remove(i, ""))}>Remove…</button>
            </div>
            {removing?.index === i ? (
              <div className="alert info row form-row" role="group" aria-label={`Remove ${c.name}`}>
                <Field label={`Move the ${c.reports.length} report${c.reports.length === 1 ? "" : "s"} of ${c.name} to`}>
                  <select value={removing.target} onChange={(e) => setRemoving({ index: i, target: e.target.value })}>
                    {cats.map((x, j) => (j === i ? null : <option key={j} value={j}>{x.name}</option>))}
                    {cats.some((x, j) => j !== i && x.name.toLowerCase() === "other") ? null : <option value="__other">Other (a new category)</option>}
                  </select>
                </Field>
                <button type="button" className="primary small" onClick={() => remove(i, removing.target)}>Remove {c.name}</button>
                <button type="button" className="small" onClick={() => setRemoving(null)}>Keep it</button>
              </div>
            ) : null}
            {c.reports.length ? (
              <ul className="rs-reports">
                {c.reports.map((r, k) => (
                  <li key={r} className="row">
                    <span className="grow">{nameOf(r)}</span>
                    <button type="button" className="small" aria-label={`Move ${nameOf(r)} up`} disabled={k === 0}
                            onClick={() => edit(cats.map((x, j) => (j === i ? { ...x, reports: move(x.reports, k, -1) } : x)))}>↑</button>
                    <button type="button" className="small" aria-label={`Move ${nameOf(r)} down`} disabled={k === c.reports.length - 1}
                            onClick={() => edit(cats.map((x, j) => (j === i ? { ...x, reports: move(x.reports, k, 1) } : x)))}>↓</button>
                    <select aria-label={`Category of ${nameOf(r)}`} value={i} onChange={(e) => moveReport(i, r, Number(e.target.value))}>
                      {cats.map((x, j) => <option key={j} value={j}>{x.name || `Category ${j + 1}`}</option>)}
                    </select>
                  </li>
                ))}
              </ul>
            ) : <p className="muted">No reports — hidden in the catalog.</p>}
          </li>
        ))}
      </ol>
      {cats.length < v.max_categories ? (
        <div className="row form-row">
          <Field label="New category"><input maxLength={v.max_name} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Board packet" /></Field>
          <button type="button" onClick={add} disabled={!newName.trim()}>Add category</button>
        </div>
      ) : null}
      <div className="actions left">
        <button type="button" className="primary" onClick={save}>{scheme === active ? "Save" : `Save and group by ${current.label}`}</button>
        <button type="button" onClick={reset} disabled={!current.customized}>Reset to defaults</button>
        {saved ? <span className="hint" role="status">Saved.</span> : dirty ? <span className="hint">Unsaved changes</span> : null}
      </div>
    </section>
  );
}
