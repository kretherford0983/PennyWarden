/** 2.0.0 (#165, #166): cover letter and #10 envelope templates on the Administrator's Check Printing setup screen.
 * Text sections use the pattern syntax with autocomplete; test prints use sample data only (BR-003). */
import { useState } from "react";
import { api } from "../api";
import { ErrorBox, Field } from "../components";
import { PatternInput, PdfViewer, usePdf } from "./checkShared";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const DOC_FONTS: [string, string][] = [["CARLITO", "Carlito (Calibri-compatible)"], ["SANS", "Liberation Sans (Arial-compatible)"], ["SERIF", "Liberation Serif (Times-compatible)"]];

export function DocumentsSection({ setup, onChanged }: { setup: any; onChanged: () => void }) {
  const [err, setErr] = useState<unknown>(null);
  const [editing, setEditing] = useState<any>(null);
  const act = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); onChanged(); } catch (x) { setErr(x); } };
  const create = (kind: "LETTER" | "ENVELOPE") => act(async () => setEditing(await api.post("/api/checks/documents", { kind })));
  const docs = setup.documents || [];
  const table = (kind: string, label: string) => {
    const list = docs.filter((d: any) => d.kind === kind);
    return (
      <>
        <h3>{label}</h3>
        {list.length ? (
          <table className="table compact">
            <thead><tr><th>Name</th><th>Default</th><th>Status</th><th /></tr></thead>
            <tbody>
              {list.map((d: any) => (
                <tr key={d.id}>
                  <td>{d.name}</td><td>{d.is_default ? "Default" : ""}</td>
                  <td>{d.active ? "Active" : <span className="badge grey">Deactivated</span>}</td>
                  <td className="actions-cell">
                    <button className="small" onClick={() => setEditing(d)}>Edit</button>{" "}
                    {d.active && !d.is_default ? <button className="small" onClick={() => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { is_default: true }))}>Make default</button> : null}{" "}
                    <button className="small" onClick={() => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { active: !d.active }))}>{d.active ? "Deactivate" : "Activate"}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">None yet.</p>}
        <div className="actions left"><button onClick={() => create(kind as any)}>{kind === "LETTER" ? "New cover letter" : "New #10 envelope"}</button></div>
      </>
    );
  };
  if (editing) {
    const Editor = editing.kind === "LETTER" ? LetterEditor : EnvelopeEditor;
    return <Editor setup={setup} doc={editing} onClose={() => { setEditing(null); onChanged(); }} onSaved={(d: any) => { setEditing(d); onChanged(); }} />;
  }
  return (
    <section className="card" aria-labelledby="docs-h">
      <h2 id="docs-h">Cover letters and envelopes</h2>
      <p className="hint">Optional: a cover letter listing the invoices paid, and a #10 envelope addressed to the payee. Register Users choose them when they print
        a check — or print them alone when the check is written by hand. Printed letters and envelopes are attached to the transaction.</p>
      <ErrorBox error={err} />
      {table("LETTER", "Cover letters")}
      {table("ENVELOPE", "Envelopes")}
    </section>
  );
}

function useEditor(doc: any, onSaved: (d: any) => void) {
  const [cfg, setCfg] = useState<any>(clone(doc.config));
  const [name, setName] = useState(doc.name);
  const [err, setErr] = useState<unknown>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState(false);
  const change = (fn: (c: any) => void) => { const c = clone(cfg); fn(c); setCfg(c); setDirty(true); setSaved(false); };
  const save = async () => {
    setErr(null);
    try { const d = await api.put(`/api/checks/documents/${doc.id}`, { name, config: cfg }); setDirty(false); setSaved(true); onSaved(d); } catch (x) { setErr(x); }
  };
  const test = async () => {
    setErr(null);
    try { setPdf(await api.postBlob(`/api/checks/documents/${doc.id}/test-print`, { config: cfg }), `${doc.kind.toLowerCase()}-test.pdf`); setViewing(true); } catch (x) { setErr(x); }
  };
  return { cfg, change, name, setName: (v: string) => { setName(v); setDirty(true); }, err, dirty, saved, save, test, pdf, viewing, setViewing, reset: () => { setCfg(clone(doc.config)); setName(doc.name); setDirty(false); } };
}

function EditorFrame({ title, e, onClose, children, singleFeed }: { title: string; e: ReturnType<typeof useEditor>; onClose: () => void; children: React.ReactNode; singleFeed?: boolean }) {
  return (
    <div className="check-setup">
      <div className="row space-between">
        <h1>{title}</h1>
        <button onClick={() => { if (!e.dirty || window.confirm("Leave without saving your changes?")) onClose(); }}>Back to Payments Setup</button>
      </div>
      <ErrorBox error={e.err} />
      {children}
      <div className="actions sticky-actions">
        {e.saved ? <span className="hint" role="status">Saved.</span> : null}
        <button onClick={e.test}>Test print (sample data)</button>
        <button onClick={e.reset} disabled={!e.dirty}>Undo changes</button>
        <button className="primary" onClick={e.save} disabled={!e.dirty}>Save</button>
      </div>
      {e.pdf && e.viewing ? <PdfViewer pdf={e.pdf} title="Test print" singleFeed={singleFeed} onClose={() => e.setViewing(false)} /> : null}
    </div>
  );
}

function Lines({ label, lines, max, onChange, variables, idBase }: { label: string; lines: string[]; max: number; onChange: (l: string[]) => void; variables: any[]; idBase: string }) {
  return (
    <fieldset className="lines">
      <legend>{label}</legend>
      {lines.map((l, i) => (
        <div key={i} className="row form-row">
          <PatternInput id={`${idBase}-${i}`} label={`${label} line ${i + 1}`} value={l} variables={variables} hint={false} onChange={(v) => onChange(lines.map((x, j) => (j === i ? v : x)))} />
          <button type="button" className="small" onClick={() => onChange(lines.filter((_, j) => j !== i))} aria-label={`Remove ${label.toLowerCase()} line ${i + 1}`}>Remove</button>
        </div>
      ))}
      {lines.length < max ? <button type="button" className="small" onClick={() => onChange([...lines, ""])}>+ Add line</button> : null}
    </fieldset>
  );
}

function LetterEditor({ setup, doc, onClose, onSaved }: { setup: any; doc: any; onClose: () => void; onSaved: (d: any) => void }) {
  const e = useEditor(doc, onSaved);
  const c = e.cfg;
  const vars = setup.letter_variables;
  const cols: any[] = c.columns;
  const allCols: any[] = setup.letter_columns;
  const unused = allCols.filter((x) => !cols.some((y) => y.key === x.key));
  const move = (i: number, d: number) => e.change((x) => { const [it] = x.columns.splice(i, 1); x.columns.splice(i + d, 0, it); });
  return (
    <EditorFrame title={`Cover letter: ${doc.name}`} e={e} onClose={onClose}>
      <section className="card">
        <div className="row form-row">
          <Field label="Name"><input maxLength={80} value={e.name} onChange={(ev) => e.setName(ev.target.value)} /></Field>
          <Field label="Font"><select value={c.font} onChange={(ev) => e.change((x) => { x.font = ev.target.value; })}>{DOC_FONTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Size (pt)"><input type="number" min={8} max={14} step={0.5} value={c.size} onChange={(ev) => e.change((x) => { x.size = Number(ev.target.value) || 11; })} /></Field>
          <label className="check"><input type="checkbox" checked={c.include_by_default} onChange={(ev) => e.change((x) => { x.include_by_default = ev.target.checked; })} /> "Include cover letter" starts ticked on the print screen</label>
        </div>
      </section>
      <section className="card">
        <h2>Letterhead</h2>
        <Lines label="Letterhead" idBase="lh" lines={c.letterhead} max={6} variables={vars} onChange={(l) => e.change((x) => { x.letterhead = l; })} />
        <p className="hint">The first line prints in bold. <code>{"{ORG}"}</code> is the organization's name. Typical lines: street, town, phone, email.</p>
        <label className="check"><input type="checkbox" checked={c.show_date} onChange={(ev) => e.change((x) => { x.show_date = ev.target.checked; })} /> Print today's date under the letterhead</label>
      </section>
      <section className="card">
        <h2>Text</h2>
        <p className="hint">The payee's name and address (from the payee's entity) print under "To:". Type <code>{"{"}</code> for the variables; a blank line starts a new paragraph.</p>
        <PatternInput id="subject" label="Subject" value={c.subject} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.subject = v; })} />
        <PatternInput id="salutation" label="Salutation" value={c.salutation} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.salutation = v; })} />
        <PatternInput id="opening" label="Opening paragraph" multiline maxLength={2000} value={c.opening} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.opening = v; })} />
        <h3>Invoice table</h3>
        <table className="table compact">
          <thead><tr><th>Column</th><th>Heading</th><th /></tr></thead>
          <tbody>
            {cols.map((col, i) => (
              <tr key={col.key}>
                <td>{allCols.find((x) => x.key === col.key)?.heading}</td>
                <td><input aria-label={`Heading for ${col.key}`} maxLength={40} value={col.heading} onChange={(ev) => e.change((x) => { x.columns[i].heading = ev.target.value; })} /></td>
                <td className="actions-cell">
                  <button className="small" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move left">↑</button>{" "}
                  <button className="small" disabled={i === cols.length - 1} onClick={() => move(i, 1)} aria-label="Move right">↓</button>{" "}
                  <button className="small" disabled={cols.length === 1} onClick={() => e.change((x) => { x.columns.splice(i, 1); })}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {unused.length ? (
          <div className="row form-row">
            {unused.map((u) => <button key={u.key} className="small" onClick={() => e.change((x) => { x.columns.push({ key: u.key, heading: u.heading }); })}>+ {u.heading}</button>)}
          </div>
        ) : null}
        <Field label="Total line label"><input maxLength={60} value={c.total_label} onChange={(ev) => e.change((x) => { x.total_label = ev.target.value; })} /></Field>
        <PatternInput id="closing" label="Closing paragraph(s)" multiline maxLength={2000} value={c.closing} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.closing = v; })} />
        <PatternInput id="signoff" label="Sign-off" value={c.signoff} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.signoff = v; })} />
      </section>
      <section className="card">
        <h2>Signed by</h2>
        <p className="hint">The letter is signed (by name — never the signature image) by the check's signer: name, title and organization. When the check prints
          without a signer, these are used instead:</p>
        <div className="row form-row">
          <PatternInput id="fbname" label="Name when there is no signer" value={c.fallback_name} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.fallback_name = v; })} />
          <PatternInput id="fbrole" label="Role when there is no signer" value={c.fallback_role} variables={vars} hint={false} placeholder="e.g. Treasurer, {ORG}" onChange={(v) => e.change((x) => { x.fallback_role = v; })} />
        </div>
      </section>
    </EditorFrame>
  );
}

function EnvelopeEditor({ setup, doc, onClose, onSaved }: { setup: any; doc: any; onClose: () => void; onSaved: (d: any) => void }) {
  const e = useEditor(doc, onSaved);
  const c = e.cfg;
  const n = (k: string) => (ev: any) => e.change((x) => { x[k] = Number(ev.target.value) || 0; });
  return (
    <EditorFrame title={`Envelope: ${doc.name}`} e={e} onClose={onClose} singleFeed>
      <section className="card">
        <div className="row form-row">
          <Field label="Name"><input maxLength={80} value={e.name} onChange={(ev) => e.setName(ev.target.value)} /></Field>
          <Field label="Width (in)"><input type="number" step={0.125} value={c.width} onChange={n("width")} /></Field>
          <Field label="Height (in)"><input type="number" step={0.125} value={c.height} onChange={n("height")} /></Field>
          <Field label="Font"><select value={c.font} onChange={(ev) => e.change((x) => { x.font = ev.target.value; })}>{DOC_FONTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Size (pt)"><input type="number" min={8} max={14} step={0.5} value={c.size} onChange={n("size")} /></Field>
          <label className="check"><input type="checkbox" checked={c.upper} onChange={(ev) => e.change((x) => { x.upper = ev.target.checked; })} /> Capitals</label>
        </div>
        <p className="hint">#10 envelope: 9.5 × 4.125 in. The payee's name and address come from the payee's entity.</p>
      </section>
      <section className="card">
        <h2>Return address</h2>
        <label className="check"><input type="checkbox" checked={c.return_address} onChange={(ev) => e.change((x) => { x.return_address = ev.target.checked; })} /> Print the return address (turn off for envelopes with a pre-printed return address; it can be switched for one print)</label>
        <Lines label="Return address" idBase="ret" lines={c.return_lines} max={5} variables={setup.envelope_variables} onChange={(l) => e.change((x) => { x.return_lines = l; })} />
      </section>
      <section className="card">
        <h2>Positions (inches from the envelope's top-left corner)</h2>
        <div className="row form-row">
          <Field label="Return address – left"><input type="number" step={0.0625} value={c.return_x} onChange={n("return_x")} /></Field>
          <Field label="Return address – top"><input type="number" step={0.0625} value={c.return_y} onChange={n("return_y")} /></Field>
          <Field label="Payee address – left"><input type="number" step={0.0625} value={c.address_x} onChange={n("address_x")} /></Field>
          <Field label="Payee address – top"><input type="number" step={0.0625} value={c.address_y} onChange={n("address_y")} /></Field>
        </div>
      </section>
      <section className="card">
        <h2>Feeding</h2>
        <div className="row form-row">
          <Field label="Which end goes in first"><select value={c.lead} onChange={(ev) => e.change((x) => { x.lead = ev.target.value; })}><option value="STAMP_END">Stamp end first</option><option value="OTHER_END">Return-address end first</option></select></Field>
          <Field label="Page size"><select value={c.page} onChange={(ev) => e.change((x) => { x.page = ev.target.value; })}><option value="LETTER">Letter page (no printer setup needed)</option><option value="ENVELOPE">Envelope-sized page</option></select></Field>
          {c.page === "LETTER" ? <Field label="Manual-feed guides"><select value={c.guide} onChange={(ev) => e.change((x) => { x.guide = ev.target.value; })}><option value="CENTER">Center the envelope</option><option value="LEFT">Against the left guide</option><option value="RIGHT">Against the right guide</option></select></Field> : null}
          <Field label="Offset right (in)"><input type="number" step={0.0625} min={-0.5} max={0.5} value={c.dx} onChange={n("dx")} /></Field>
          <Field label="Offset down (in)"><input type="number" step={0.0625} min={-0.5} max={0.5} value={c.dy} onChange={n("dy")} /></Field>
        </div>
        <Field label="Printer note (shown when printing)"><input maxLength={200} value={c.note || ""} onChange={(ev) => e.change((x) => { x.note = ev.target.value || null; })} /></Field>
      </section>
    </EditorFrame>
  );
}

