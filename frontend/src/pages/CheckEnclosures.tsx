/** 2.0.0 (#165, #166): print the cover letter and #10 envelope for a payment - after printing its check, or on their
 * own when the check is written by hand. Printed letters and envelopes are attached to the transaction. */
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading, useConfirmable } from "../components";
import { PdfViewer, usePdf } from "./checkShared";

const STEP = 0.0625;

export function EnclosuresPanel({ txnId, signerId, onChanged, intro }: { txnId: number; signerId: number | null; onChanged: () => void; intro?: string }) {
  const [docs, setDocs] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [letterId, setLetterId] = useState("");
  const [include, setInclude] = useState(false);
  const [envId, setEnvId] = useState("");
  const [useReturn, setUseReturn] = useState(false);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState<null | "letter" | "envelope" | "envtest">(null);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [adjust, setAdjust] = useState(false);
  const [envAnyway, setEnvAnyway] = useState(false);
  // 2.1.0 (#247): fold marks for this letter - filled in from the user's own default, else the template's
  const [fold, setFold] = useState("NONE");
  const [foldSettings, setFoldSettings] = useState(false);
  const { run, dialog } = useConfirmable();
  const load = () => api.get(`/api/checks/transactions/${txnId}/documents`).then((d) => {
    setDocs(d);
    const l = d.letters.find((x: any) => x.is_default) || d.letters[0];
    const e = d.envelopes.find((x: any) => x.is_default) || d.envelopes[0];
    setLetterId((cur) => { if (!cur && l) setInclude(l.include_by_default !== false); return cur || (l ? String(l.id) : ""); });
    setEnvId((cur) => { const id = cur || (e ? String(e.id) : ""); const en = d.envelopes.find((x: any) => String(x.id) === id); if (en && !cur) setUseReturn(!!en.return_address); return id; });
  }, setErr);
  useEffect(() => { load(); }, [txnId]); // eslint-disable-line react-hooks/exhaustive-deps
  const foldDefault = docs?.letters.find((x: any) => String(x.id) === letterId)?.fold_default || "NONE";
  useEffect(() => { setFold(foldDefault); }, [letterId, foldDefault]);
  if (!docs) return err ? <ErrorBox error={err} /> : <Loading />;
  if (!docs.letters.length && !docs.envelopes.length) return null;
  const env = docs.envelopes.find((x: any) => String(x.id) === envId);
  // build 13 (#230): a letter for a #10 double-window envelope carries the addresses itself - choosing one hides the
  // envelope (it can still be printed on request); choosing a standard letter brings the envelope back
  const letter = docs.letters.find((x: any) => String(x.id) === letterId);
  const windowLetter = !!(include && letter?.window && letter.window !== "NONE");
  const showEnvelope = docs.envelopes.length > 0 && (!windowLetter || envAnyway);
  const printLetter = async () => {
    setErr(null);
    try {
      const blob = await run((c) => api.postBlob(`/api/checks/transactions/${txnId}/letter`, { document_id: Number(letterId), signer_id: signerId, fold_marks: fold, confirmations: c }));
      if (!blob) return;
      setPdf(blob, "cover-letter.pdf"); setViewing("letter"); setDone((s) => new Set(s).add("letter")); onChanged();
    } catch (x) { setErr(x); }
  };
  const printEnvelope = async (test: boolean) => {
    setErr(null);
    try {
      const blob = await run((c) => api.postBlob(`/api/checks/transactions/${txnId}/${test ? "envelope-test" : "envelope"}`, { document_id: Number(envId), return_address: useReturn, confirmations: c }));
      if (!blob) return;
      setPdf(blob, test ? "envelope-test.pdf" : "envelope.pdf"); setViewing(test ? "envtest" : "envelope");
      if (!test) { setDone((s) => new Set(s).add("envelope")); onChanged(); }
    } catch (x) { setErr(x); }
  };
  return (
    <section className="card enclosures" aria-labelledby="encl-h">
      <h3 id="encl-h">Cover letter and envelope</h3>
      {intro ? <p className="hint">{intro}</p> : null}
      <ErrorBox error={err} />
      {docs.letters.length ? (
        <label className="check"><input type="checkbox" checked={include} onChange={(e) => setInclude(e.target.checked)} /> Include cover letter</label>
      ) : null}
      {docs.letters.length && include ? (
        <div className="row form-row">
          <Field label="Cover letter">
            <select value={letterId} onChange={(e) => setLetterId(e.target.value)}>{docs.letters.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
          </Field>
          <Field label="Fold marks">
            <select value={fold} onChange={(e) => setFold(e.target.value)} aria-label="Fold marks">
              <option value="NONE">None</option>
              <option value="FRONT">On the front</option>
              <option value="BACK">On the back (two-sided)</option>
            </select>
          </Field>
          <button onClick={printLetter} disabled={!letterId}>{done.has("letter") ? "Print the cover letter again" : "Print cover letter"}</button>
          {done.has("letter") ? <span className="badge green">Attached</span> : null}
        </div>
      ) : null}
      {docs.letters.length && include && fold === "BACK" ? (
        <div className="alert warn" role="alert" data-testid="fold-back-banner"><b>Print on both sides of the paper (flip on long edge).</b> The fold
          marks print on the back of the first sheet. Make sure the printer can print two-sided and is set to; printed one-sided,
          the fold marks come out on a separate sheet.</div>
      ) : null}
      {docs.letters.length && include ? (
        <p className="hint">Fold marks: small ticks at the edges to fold the letter in even thirds.{" "}
          <button className="link small" onClick={() => setFoldSettings((v) => !v)}>{foldSettings ? "Hide" : "My letter printer settings"}{docs.my_letter_fold !== "TEMPLATE" ? " (adjusted)" : ""}</button></p>
      ) : null}
      {foldSettings ? <LetterPrinter current={docs.my_letter_fold} onSaved={load} /> : null}
      {windowLetter ? (
        <p className="hint" data-testid="window-letter-note"><b>Window envelope letter:</b> the addresses print on the letter and show
          through a #10 double-window envelope, so there is no envelope to print.
          {docs.envelopes.length && !envAnyway ? <>{" "}<button className="link small" onClick={() => setEnvAnyway(true)}>Print an envelope anyway</button></> : null}</p>
      ) : null}
      {showEnvelope ? (
        <>
          <div className="row form-row">
            <Field label="Envelope">
              <select value={envId} onChange={(e) => { setEnvId(e.target.value); const en = docs.envelopes.find((x: any) => String(x.id) === e.target.value); setUseReturn(!!en?.return_address); }}>
                {docs.envelopes.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
            <label className="check"><input type="checkbox" checked={useReturn} onChange={(e) => setUseReturn(e.target.checked)} /> Print the return address</label>
            <button onClick={() => printEnvelope(false)} disabled={!envId}>{done.has("envelope") ? "Print the envelope again" : "Print envelope"}</button>
            {done.has("envelope") ? <span className="badge green">Attached</span> : null}
          </div>
          {env ? (
            <p className="hint">{env.note || "Feed the envelope through the manual feed."}{" "}
              <button className="link small" onClick={() => printEnvelope(true)}>Test on plain paper</button>{" · "}
              <button className="link small" onClick={() => setAdjust((a) => !a)}>{adjust ? "Hide" : "My envelope printer settings"}{env.printer?.customized ? " (adjusted)" : ""}</button></p>
          ) : null}
          {adjust && env ? <EnvelopePrinter env={env} onSaved={load} /> : null}
        </>
      ) : null}
      {pdf && viewing ? (
        <PdfViewer pdf={pdf} singleFeed={viewing !== "letter"} onClose={() => setViewing(null)}
          title={viewing === "letter" ? "Cover letter" : viewing === "envelope" ? "Envelope" : "Envelope test (plain paper)"}>
          {viewing === "envtest" ? <p className="hint">Print on plain paper, fold or hold it against an envelope to check where the address lands. It is not recorded.</p> : null}
        </PdfViewer>
      ) : null}
      {dialog}
    </section>
  );
}

/** 2.1.0 (#247): the user's own default for cover-letter fold marks (My Printer Settings). */
function LetterPrinter({ current, onSaved }: { current: string; onSaved: () => void }) {
  const [v, setV] = useState(current);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const save = async () => {
    setErr(null); setSaved(false);
    try { await api.put("/api/checks/my-printer/letter", { fold_marks: v }); setSaved(true); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <div className="card subtle" data-testid="letter-printer">
      <p className="hint">This setting is yours only. Choose <i>On the back</i> only if your printer prints two-sided.</p>
      <ErrorBox error={err} />
      <Field label="Fold marks on my letters">
        <select value={v} onChange={(e) => { setV(e.target.value); setSaved(false); }} aria-label="Fold marks on my letters">
          <option value="TEMPLATE">Use the template's setting</option>
          <option value="FRONT">On the front</option>
          <option value="BACK">On the back (my printer prints two-sided)</option>
        </select>
      </Field>
      <div className="row form-row"><button onClick={save}>Save my setting</button>{saved ? <span className="hint" role="status">Saved.</span> : null}</div>
    </div>
  );
}

function EnvelopePrinter({ env, onSaved }: { env: any; onSaved: () => void }) {
  const p = env.printer || {};
  const [page, setPage] = useState<string>(p.page || env.page || "LETTER");
  const [guide, setGuide] = useState<string>(p.guide || env.guide || "CENTER");
  const [dx, setDx] = useState<number>(p.dx || 0);
  const [dy, setDy] = useState<number>(p.dy || 0);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const save = async () => {
    setErr(null); setSaved(false);
    try { await api.put("/api/checks/my-printer/envelope", { document_id: env.id, page, guide, dx, dy }); setSaved(true); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <div className="card subtle">
      <p className="hint">These settings are yours only (this envelope template). Move the print by up to 1/4 inch if the address lands off-center.</p>
      <ErrorBox error={err} />
      <div className="row form-row">
        <Field label="Page size"><select value={page} onChange={(e) => setPage(e.target.value)}><option value="LETTER">Letter page</option><option value="ENVELOPE">Envelope-sized page</option></select></Field>
        {page === "LETTER" ? <Field label="Manual-feed guides"><select value={guide} onChange={(e) => setGuide(e.target.value)}><option value="CENTER">Centered</option><option value="LEFT">Left guide</option><option value="RIGHT">Right guide</option></select></Field> : null}
        <Field label="Move right (in)"><input type="number" step={STEP} min={-0.25} max={0.25} value={dx} onChange={(e) => setDx(Number(e.target.value) || 0)} /></Field>
        <Field label="Move down (in)"><input type="number" step={STEP} min={-0.25} max={0.25} value={dy} onChange={(e) => setDy(Number(e.target.value) || 0)} /></Field>
        <button onClick={save}>Save my settings</button>
        {saved ? <span className="hint" role="status">Saved.</span> : null}
      </div>
    </div>
  );
}

/** The check is written by hand: record its number (typed twice), then print the letter and envelope. */
export function HandwrittenPanel({ txn, nextNumber, signerId, onChanged }: { txn: any; nextNumber: string | null; signerId: number | null; onChanged: () => void }) {
  const [no, setNo] = useState<string>(txn.check_number || nextNumber || "");
  const [again, setAgain] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [recorded, setRecorded] = useState<string | null>(txn.check_number || null);
  const save = async () => {
    setErr(null);
    try { const r = await api.post(`/api/checks/transactions/${txn.id}/handwritten`, { check_number: no.trim(), confirm_check_number: again.trim() }); setRecorded(r.check_number); setAgain(""); onChanged(); } catch (x) { setErr(x); }
  };
  return (
    <div className="handwritten">
      <section className="card">
        <h3>Check written by hand</h3>
        <p className="hint">No check is printed. Record the number of the check you wrote so the register matches the bank, then print the cover letter and
          envelope below.</p>
        <ErrorBox error={err} />
        {recorded ? <p role="status">Check number <b>#{recorded}</b> is recorded for this payment.</p> : null}
        <div className="row form-row">
          <Field label="Check number you wrote" hint={nextNumber && !recorded ? `The next unused number in this account is ${nextNumber}.` : undefined}>
            <input maxLength={20} value={no} onChange={(e) => setNo(e.target.value)} />
          </Field>
          <Field label="Type the check number again"><input maxLength={20} value={again} onChange={(e) => setAgain(e.target.value)} aria-invalid={!!again && again.trim() !== no.trim()} /></Field>
          <button onClick={save} disabled={!no.trim() || again.trim() !== no.trim() || no.trim() === recorded}>{recorded ? "Change the number" : "Record check number"}</button>
        </div>
        {again && again.trim() !== no.trim() ? <p className="error-text" role="alert">The two numbers don't match.</p> : null}
      </section>
      <EnclosuresPanel txnId={txn.id} signerId={signerId} onChanged={onChanged} />
    </div>
  );
}
