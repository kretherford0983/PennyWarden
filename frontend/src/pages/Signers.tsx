/** 2.3.0 (#395): the shared Signers page (Administrators, shown when Payments or Donations is on). One list of signers
 * for checks, payment cover letters and donation receipts/statements, each with *Used for* tags like the envelope
 * library. A signer in use somewhere can't be retired or lose that area's tag until those settings change.
 * Moved here from Payments Setup (#159). */
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, Field, GuardedForm, Loading, Modal, RowMenu } from "../components";

export default function SignersPage() {
  const [lib, setLib] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [add, setAdd] = useState(false);
  const [edit, setEdit] = useState<any>(null);
  const [tags, setTags] = useState<any>(null);
  const [v, setV] = useState(0);
  const load = () => api.get("/api/signers").then(setLib, setErr);
  useEffect(() => { load(); }, []);
  const act = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); setV(v + 1); load(); } catch (x) { setErr(x); } };
  if (!lib) return <><ErrorBox error={err} /><Loading /></>;
  const label = (a: string) => lib.areas.find((x: any) => x.id === a)?.label || a;
  return (
    <div className="page">
      <h1>Signers</h1>
      <p className="hint">One list of signers for checks, payment cover letters and donation receipts and statements. Tag each signer
        for the areas they sign; each area's settings offer only the signers tagged for it.
        A signature image (PNG) is stored encrypted and can never be downloaded again – only a small preview marked SAMPLE is shown.
        It prints only on real checks and printed letters (never on the copy kept with the record), and every print that uses it is recorded in the audit log.</p>
      <ErrorBox error={err} />
      <section className="card" aria-labelledby="signers-h">
        <h2 id="signers-h">Signers and signatures</h2>
        {lib.signers.length ? (
          <table className="table compact">
            <thead><tr><th>Name</th><th>Title</th><th>Signature</th><th>Used for</th><th>Status</th><th /></tr></thead>
            <tbody>
              {lib.signers.map((x: any) => (
                <tr key={x.id}>
                  <td>{x.name}</td><td>{x.title || ""}</td>
                  <td>{x.has_image ? <img src={`/api/signers/${x.id}/preview?v=${v}-${x.image_uploaded_at}`} alt={`Sample of ${x.name}'s signature`} height={40} /> : <span className="muted">No image</span>}</td>
                  <td>{x.areas.length ? x.areas.map((a: string) => <span key={a} className="badge">{label(a)}</span>) : <span className="muted">Not used</span>}
                    {x.in_use.length ? <div className="hint">In use: {x.in_use.join(", ")}</div> : null}</td>
                  <td>{x.active ? "Active" : <span className="badge grey">Retired</span>}</td>
                  <td className="actions-cell">
                    <button className="small" onClick={() => setEdit(x)}>Edit…</button>
                    <input type="file" accept="image/png" hidden id={`signer-image-${x.id}`} aria-label={`Signature image for ${x.name}`} onChange={(e) => {
                      const f = e.target.files?.[0]; e.target.value = "";
                      if (f) act(() => api.upload(`/api/signers/${x.id}/image`, f));
                    }} />
                    <RowMenu name={x.name} actions={[
                      { label: "Used for…", onClick: () => setTags(x) },
                      { label: x.has_image ? "Replace image…" : "Upload image…", onClick: () => (document.getElementById(`signer-image-${x.id}`) as HTMLInputElement | null)?.click() },
                      x.has_image && { label: "Remove image", onClick: () => window.confirm(`Remove ${x.name}'s signature image?`) && act(() => api.post(`/api/signers/${x.id}/image/remove`)), danger: true },
                      x.active ? { label: "Retire", onClick: () => act(() => api.post(`/api/signers/${x.id}/active`, { active: false })), danger: true }
                        : { label: "Bring back", onClick: () => act(() => api.post(`/api/signers/${x.id}/active`, { active: true })) },
                    ]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">No signers yet.</p>}
        <div className="actions left"><button onClick={() => setAdd(true)}>Add signer…</button></div>
      </section>
      {add ? <SignerForm areas={lib.areas} onClose={() => setAdd(false)} onDone={() => { setAdd(false); load(); }} /> : null}
      {edit ? <SignerForm signer={edit} areas={lib.areas} onClose={() => setEdit(null)} onDone={() => { setEdit(null); load(); }} /> : null}
      {tags ? <AreasForm signer={tags} areas={lib.areas} onClose={() => setTags(null)} onDone={() => { setTags(null); load(); }} /> : null}
    </div>
  );
}

function AreaBoxes({ areas, value, onChange, locked = [] }: { areas: any[]; value: string[]; onChange: (v: string[]) => void; locked?: string[] }) {
  return (
    <fieldset className="checks">
      <legend>Used for</legend>
      {areas.map((a: any) => (
        <label key={a.id} className="check">
          <input type="checkbox" checked={value.includes(a.id)} disabled={locked.includes(a.id) || (!a.enabled && !value.includes(a.id))}
            onChange={(e) => onChange(e.target.checked ? [...value, a.id] : value.filter((x) => x !== a.id))} />
          {a.label}{!a.enabled ? <span className="muted"> (module off)</span> : null}{locked.includes(a.id) ? <span className="muted"> (in use)</span> : null}
        </label>
      ))}
    </fieldset>
  );
}

function AreasForm({ signer, areas, onClose, onDone }: { signer: any; areas: any[]; onClose: () => void; onDone: () => void }) {
  const [value, setValue] = useState<string[]>(signer.areas);
  const [err, setErr] = useState<unknown>(null);
  const go = async (e: FormEvent) => {
    e.preventDefault(); setErr(null);
    try { await api.put(`/api/signers/${signer.id}/areas`, { areas: value }); onDone(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`${signer.name} – used for`} onClose={onClose}>
      <GuardedForm onSubmit={go}>
        <ErrorBox error={err} />
        <AreaBoxes areas={areas} value={value} onChange={setValue} locked={signer.in_use_areas} />
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

function SignerForm({ signer, areas, onClose, onDone }: { signer?: any; areas: any[]; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(signer?.name || "");
  const [title, setTitle] = useState(signer?.title || "");
  const [tags, setTags] = useState<string[]>(areas.filter((a: any) => a.enabled).map((a: any) => a.id));
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const go = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      if (signer) await api.put(`/api/signers/${signer.id}`, { name, title: title || null });
      else {
        const fd = new FormData();
        fd.append("name", name);
        if (title) fd.append("title", title);
        fd.append("areas", tags.join(","));
        if (file) fd.append("file", file);
        await api.postForm("/api/signers", fd);
      }
      onDone();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={signer ? `Edit ${signer.name}` : "Add signer"} onClose={onClose}>
      <GuardedForm onSubmit={go}>
        <ErrorBox error={err} />
        <Field label="Name (prints on record copies as 'SIGNATURE ON FILE: NAME')"><input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Title (optional)"><input maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Treasurer" /></Field>
        {!signer ? <AreaBoxes areas={areas} value={tags} onChange={setTags} /> : null}
        {!signer ? <Field label="Signature image (PNG, optional now)" hint="A scan or photo of the signature on white paper, cropped close. Transparent backgrounds work best.">
          <input type="file" accept="image/png" onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}
