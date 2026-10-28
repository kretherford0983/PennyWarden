/** 2.2.0 (#325): the shared envelope library (Kyle, 2026-10-23).
 * - EnvelopeLibrary: a feature's own envelope list on its setup page (Payments Setup, Donations Setup) - the templates
 *   tagged for it, with its default, and the other templates of the library, which can be added to it. A feature's
 *   page removes only its own tag.
 * - EnvelopesPage: the global Envelopes page (Administrators, shown when Payments or Donations is on) - every template
 *   with what it is used for; any tag can be added or removed; an untagged template stays as *Not used* (never
 *   deleted: printed copies refer to it).
 * - ReceiptEnvelopePanel: print a donor's envelope after a receipt (Donations page and a deposit's dialog), like the
 *   cover letter's envelope. Kept with the donation and on its deposit. */
import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { ErrorBox, Field, Loading, Modal, RowMenu, useConfirmable } from "../components";
import { DocFocus, DocumentEditor } from "./CheckDocuments";
import { EnvelopePrinter } from "./CheckEnclosures";
import { PdfViewer, usePdf } from "./checkShared";

export type Feature = "PAYMENTS" | "DONATIONS";
export const FEATURE_LABEL: Record<string, string> = { PAYMENTS: "Payments", DONATIONS: "Donations" };

/** Removing a feature's tag: from its default, another default is chosen first (409 DEFAULT_NEEDED lists them). */
function useTagger(onChanged: () => void, setErr: (x: unknown) => void) {
  const [pick, setPick] = useState<null | { doc: any; feature: string; candidates: any[]; choice: string }>(null);
  const setTag = async (doc: any, feature: string, on: boolean, newDefault?: number) => {
    setErr(null);
    try {
      await api.post(`/api/envelopes/${doc.id}/tags`, { feature, on, new_default_id: newDefault ?? null });
      setPick(null); onChanged();
    } catch (x) {
      if (x instanceof ApiError && x.code === "DEFAULT_NEEDED") setPick({ doc, feature, candidates: x.body.candidates || [], choice: String(x.body.candidates?.[0]?.id ?? "") });
      else setErr(x);
    }
  };
  const dialog = pick ? (
    <Modal title={`Choose another ${FEATURE_LABEL[pick.feature]} default`} onClose={() => setPick(null)}>
      <p>“{pick.doc.name}” is the default envelope for {FEATURE_LABEL[pick.feature]}. Choose the envelope {FEATURE_LABEL[pick.feature]} uses from now on.</p>
      <Field label={`New ${FEATURE_LABEL[pick.feature]} default`}>
        <select value={pick.choice} onChange={(e) => setPick({ ...pick, choice: e.target.value })}>
          {pick.candidates.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </Field>
      <div className="actions">
        <button onClick={() => setPick(null)}>Cancel</button>
        <button className="primary" onClick={() => setTag(pick.doc, pick.feature, false, Number(pick.choice))}>Remove from {FEATURE_LABEL[pick.feature]}</button>
      </div>
    </Modal>
  ) : null;
  return { setTag, dialog };
}

const usedFor = (d: any) => (d.features?.length ? d.features.map((f: string) => FEATURE_LABEL[f] || f).join(", ") : "Not used");

/** A feature's envelopes on its setup page. `docs`: every envelope template of the library (doc_out). */
export function EnvelopeLibrary({ feature, docs, onChanged, onEdit, note }: {
  feature: Feature; docs: any[]; onChanged: () => void; onEdit: (doc: any, focus?: DocFocus) => void; note?: React.ReactNode;
}) {
  const [err, setErr] = useState<unknown>(null);
  const { setTag, dialog } = useTagger(onChanged, setErr);
  const label = FEATURE_LABEL[feature];
  const act = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); onChanged(); } catch (x) { setErr(x); } };
  const draft = (q: string) => act(async () => onEdit(await api.get(`/api/checks/documents/draft?kind=ENVELOPE&feature=${feature}${q}`), "name"));
  const mine = docs.filter((d) => d.kind === "ENVELOPE" && d.features?.includes(feature));
  const others = docs.filter((d) => d.kind === "ENVELOPE" && !d.features?.includes(feature) && d.active);
  return (
    <section className="card" aria-labelledby={`envelopes-${feature}-h`} data-testid={`envelopes-${feature.toLowerCase()}`}>
      <h2 id={`envelopes-${feature}-h`}>Envelopes</h2>
      <p className="hint">{feature === "PAYMENTS"
        ? "Optional: a #10 envelope addressed to the payee, printed with the check (or on its own) and attached to the transaction."
        : "Optional: a #10 envelope addressed to the donor, printed after the receipt and kept with the donation (and its deposit)."}{" "}
        Envelope templates are one library shared by Payments and Donations; each has its own default.</p>
      {note}
      <ErrorBox error={err} />
      {mine.length ? (
        <table className="table compact">
          <thead><tr><th>Name</th><th>Default</th><th>Also used for</th><th>Status</th><th /></tr></thead>
          <tbody>
            {mine.map((d: any) => (
              <tr key={d.id}>
                <td>{d.name}</td>
                <td>{d.default_for?.includes(feature) ? "Default" : ""}</td>
                <td>{d.features.filter((f: string) => f !== feature).map((f: string) => FEATURE_LABEL[f]).join(", ")}</td>
                <td>{d.active ? "Active" : <span className="badge grey">Deactivated</span>}</td>
                <td className="actions-cell">
                  <button className="small" onClick={() => onEdit(d)}>Edit</button>
                  <RowMenu name={d.name} actions={[
                    { label: "Duplicate", onClick: () => draft(`&duplicate_of=${d.id}`) },
                    d.active && !d.default_for?.includes(feature) && { label: "Make default", onClick: () => act(() => api.post(`/api/envelopes/${d.id}/default`, { feature })) },
                    { label: `Remove from ${label}`, onClick: () => setTag(d, feature, false) },
                    d.active ? { label: "Deactivate", onClick: () => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { active: false })), danger: true }
                      : { label: "Activate", onClick: () => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { active: true })) },
                  ]} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted" data-testid="no-envelope">No envelope is used for {label}, so printing an envelope is hidden there. Create one, or add one of the other templates below.</p>}
      <div className="actions left"><button onClick={() => draft("")}>New #10 envelope</button></div>
      {others.length ? (
        <>
          <h3>Other envelope templates</h3>
          <table className="table compact">
            <thead><tr><th>Name</th><th>Used for</th><th /></tr></thead>
            <tbody>
              {others.map((d: any) => (
                <tr key={d.id}>
                  <td>{d.name}</td><td>{usedFor(d)}</td>
                  <td className="actions-cell"><button className="small" onClick={() => setTag(d, feature, true)}>Add to {label}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
      {dialog}
    </section>
  );
}

/** The global Envelopes page (Administrators). */
export default function EnvelopesPage() {
  const [lib, setLib] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [editing, setEditing] = useState<any>(null);
  const [focus, setFocus] = useState<DocFocus>(undefined);
  const load = () => api.get("/api/envelopes").then(setLib, setErr);
  useEffect(() => { load(); }, []);
  const { setTag, dialog } = useTagger(load, setErr);
  if (!lib) return err ? <ErrorBox error={err} /> : <Loading />;
  const edit = (d: any, f?: DocFocus) => { setEditing(d); setFocus(f); };
  if (editing) {
    return <DocumentEditor setup={{ ...lib, documents: lib.envelopes }} doc={editing} focus={focus} feature={null} backLabel="Back to Envelopes"
                           onOpen={edit} onClose={() => { edit(null); load(); }} onSaved={(d) => { setEditing(d); setFocus(undefined); load(); }} />;
  }
  const features = lib.features.filter((f: any) => f.enabled);
  const act = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); load(); } catch (x) { setErr(x); } };
  return (
    <div className="page envelopes-page">
      <h1>Envelopes</h1>
      <p className="hint">One library of #10 envelope templates, shared by {features.map((f: any) => f.label).join(" and ")}. Each template is used for the features you
        choose, and each feature has its own default. Your envelope printer adjustments belong to the template, so they apply wherever it is used. Templates are
        never deleted: an envelope no feature uses stays here as <i>Not used</i>.</p>
      <ErrorBox error={err} />
      <table className="table compact" data-testid="envelope-library">
        <thead><tr><th>Name</th><th>Used for</th><th>Default for</th><th>Status</th><th /></tr></thead>
        <tbody>
          {lib.envelopes.map((d: any) => (
            <tr key={d.id}>
              <td>{d.name}</td>
              <td>{d.features.length ? usedFor(d) : <span className="badge grey">Not used</span>}</td>
              <td>{d.default_for.map((f: string) => FEATURE_LABEL[f]).join(", ")}</td>
              <td>{d.active ? "Active" : <span className="badge grey">Deactivated</span>}</td>
              <td className="actions-cell">
                <button className="small" onClick={() => edit(d)}>Edit</button>
                <RowMenu name={d.name} actions={[
                  ...features.map((f: any) => d.features.includes(f.id)
                    ? { label: `Remove from ${f.label}`, onClick: () => setTag(d, f.id, false) }
                    : { label: `Use for ${f.label}`, onClick: () => setTag(d, f.id, true) }),
                  ...features.filter((f: any) => d.active && d.features.includes(f.id) && !d.default_for.includes(f.id))
                    .map((f: any) => ({ label: `Make the ${f.label} default`, onClick: () => act(() => api.post(`/api/envelopes/${d.id}/default`, { feature: f.id })) })),
                  d.active ? { label: "Deactivate", onClick: () => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { active: false })), danger: true }
                    : { label: "Activate", onClick: () => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { active: true })) },
                ]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!lib.envelopes.length ? <p className="muted">None yet.</p> : null}
      <div className="actions left">
        <button onClick={() => act(async () => edit(await api.get("/api/checks/documents/draft?kind=ENVELOPE&feature=NONE"), "name"))}>New #10 envelope</button>
      </div>
      {features.map((f: any) => f.default == null ? (
        <p key={f.id} className="hint" data-testid={`no-default-${f.id.toLowerCase()}`}>{f.label} has no envelope, so printing an envelope is hidden there.</p>) : null)}
      {dialog}
    </div>
  );
}

/** "Also used for …" in the envelope editor: changes apply to every feature using the template; *Duplicate for <feature>
 * only* makes a copy for this feature (the tag, and the default, move to the copy). */
export function SharedNotice({ doc, feature, onOpen }: { doc: any; feature: string | null; onOpen: (d: any) => void }) {
  const [err, setErr] = useState<unknown>(null);
  const others = (doc.features || []).filter((f: string) => f !== feature);
  if (doc.id == null || !others.length || (feature == null && others.length < 2)) return null;
  const dup = async () => {
    setErr(null);
    try { const r = await api.post(`/api/envelopes/${doc.id}/duplicate-for`, { feature }); onOpen({ ...r.created, justCreated: true }); } catch (x) { setErr(x); }
  };
  return (
    <div className="alert info" role="note" data-testid="envelope-shared">
      <ErrorBox error={err} />
      <b>Also used for {others.map((f: string) => FEATURE_LABEL[f]).join(" and ")}:</b> changes apply there too.
      {feature ? <>{" "}<button type="button" className="linklike" onClick={dup}>Duplicate for {FEATURE_LABEL[feature]} only</button></> : null}
    </div>
  );
}

/** Print the donor's envelope for a donation (after its receipt). */
export function ReceiptEnvelopePanel({ donationId, onChanged }: { donationId: number; onChanged?: () => void }) {
  const [ch, setCh] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [envId, setEnvId] = useState("");
  const [useReturn, setUseReturn] = useState(false);
  const [anyway, setAnyway] = useState(false);
  const [adjust, setAdjust] = useState(false);
  const [done, setDone] = useState(false);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState<null | "envelope" | "test">(null);
  const { run, dialog } = useConfirmable();
  const load = () => api.get("/api/donations/envelopes").then((d) => {
    setCh(d);
    setEnvId((cur) => {
      const id = cur || (d.envelopes[0] ? String(d.envelopes[0].id) : "");
      const en = d.envelopes.find((x: any) => String(x.id) === id);
      if (en && !cur) setUseReturn(!!en.return_address);
      return id;
    });
  }, setErr);
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!ch) return err ? <ErrorBox error={err} /> : null;
  if (!ch.envelopes.length) return <p className="hint" data-testid="no-receipt-envelope">No envelope is set up for Donations. An Administrator can add one in Donations Setup.</p>;
  if (ch.receipt_window && !anyway) {
    return <p className="hint" data-testid="window-receipt-note"><b>Window envelope receipt:</b> the addresses print on the receipt and show through a #10
      double-window envelope, so there is no envelope to print.{" "}<button className="link small" onClick={() => setAnyway(true)}>Print an envelope anyway</button></p>;
  }
  const env = ch.envelopes.find((x: any) => String(x.id) === envId);
  const print = async (test: boolean) => {
    setErr(null);
    try {
      const blob = await run((c) => api.postBlob(`/api/donations/${donationId}/${test ? "envelope-test" : "envelope"}`, { document_id: Number(envId), return_address: useReturn, confirmations: c }));
      if (!blob) return;
      setPdf(blob, test ? "envelope-test.pdf" : "envelope.pdf"); setViewing(test ? "test" : "envelope");
      if (!test) { setDone(true); onChanged?.(); }
    } catch (x) { setErr(x); }
  };
  return (
    <div className="receipt-envelope" data-testid="receipt-envelope">
      <h4>Envelope</h4>
      <ErrorBox error={err} />
      <div className="row form-row">
        <Field label="Envelope">
          <select aria-label="Envelope" value={envId} onChange={(e) => { setEnvId(e.target.value); const en = ch.envelopes.find((x: any) => String(x.id) === e.target.value); setUseReturn(!!en?.return_address); }}>
            {ch.envelopes.map((d: any) => <option key={d.id} value={d.id}>{d.name}{d.is_default ? " (default)" : ""}</option>)}
          </select>
        </Field>
        <label className="check"><input type="checkbox" checked={useReturn} onChange={(e) => setUseReturn(e.target.checked)} /> Print the return address</label>
        <button onClick={() => print(false)} disabled={!envId}>{done ? "Print the envelope again" : "Print envelope"}</button>
        {done ? <span className="badge green">Kept</span> : null}
      </div>
      {env ? (
        <p className="hint">{env.note || "Feed the envelope through the manual feed."}{" "}
          <button className="link small" onClick={() => print(true)}>Test on plain paper</button>{" · "}
          <button className="link small" onClick={() => setAdjust((a) => !a)}>{adjust ? "Hide" : "My envelope printer settings"}{env.printer?.customized ? " (adjusted)" : ""}</button></p>
      ) : null}
      {adjust && env ? <EnvelopePrinter env={env} onSaved={load} url="/api/donations/my-printer/envelope" /> : null}
      {pdf && viewing ? (
        <PdfViewer pdf={pdf} singleFeed onClose={() => setViewing(null)} title={viewing === "envelope" ? "Envelope" : "Envelope test (plain paper)"}>
          {viewing === "test" ? <p className="hint">Print on plain paper, fold or hold it against an envelope to check where the address lands. It is not kept.</p> : null}
        </PdfViewer>
      ) : null}
      {dialog}
    </div>
  );
}
