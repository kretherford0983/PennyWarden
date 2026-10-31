// 2.4.0 (#249): email - the Administrator's mail server, and the one-click Send email form for invoices and
// statements (Invoice Managers). The mail server password is never shown again after saving (replace only).
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading, Modal } from "../components";

export function EmailSettingsPanel() {
  const [s, setS] = useState<any>(null);
  const [v, setV] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [test, setTest] = useState<any>(null);
  const fill = (x: any) => { setS(x); setV({ enabled: x.enabled, host: x.host || "", port: String(x.port), security: x.security, username: x.username || "", password: "", clear_password: false, from_address: x.from_address || "", from_name: x.from_name || "", reply_to: x.reply_to || "" }); };
  useEffect(() => { api.get("/api/system/email").then(fill, setErr); }, []);
  if (!s || !v) return <section className="card"><h2>Email</h2><ErrorBox error={err} />{err ? null : <Loading />}</section>;
  const set = (k: string) => (e: any) => { setSaved(false); setV({ ...v, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }); };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try { fill(await api.put("/api/system/email", { ...v, port: Number(v.port), password: v.password || null })); setSaved(true); } catch (x) { setErr(x); }
  };
  const sendTest = async () => {
    setErr(null);
    setTest(null);
    try { setTest(await api.post("/api/system/email/test", { to: testTo })); } catch (x) { setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="email-h" data-testid="email-settings">
      <h2 id="email-h">Email (outgoing mail server)</h2>
      <p className="hint">Used when an Invoice Manager emails an invoice or a statement to a customer. Nothing is ever emailed automatically. Your email provider gives these settings.</p>
      <form onSubmit={save}>
        <ErrorBox error={err} />
        <label className="check"><input type="checkbox" checked={v.enabled} onChange={set("enabled")} /> Email is turned on</label>
        <div className="row fields">
          <Field label="Mail server (SMTP)"><input maxLength={255} value={v.host} onChange={set("host")} placeholder="smtp.example.org" /></Field>
          <Field label="Port"><input type="number" min={1} max={65535} value={v.port} onChange={set("port")} style={{ width: "7em" }} /></Field>
          <Field label="Security"><select value={v.security} onChange={set("security")}><option value="STARTTLS">STARTTLS (usually port 587)</option><option value="SSL">SSL/TLS (usually port 465)</option><option value="NONE">None (not recommended)</option></select></Field>
        </div>
        <div className="row fields">
          <Field label="User name"><input maxLength={255} autoComplete="off" value={v.username} onChange={set("username")} /></Field>
          <Field label="Password" hint={s.password_saved ? "A password is saved. Leave empty to keep it." : "No password saved."}>
            <input type="password" maxLength={500} autoComplete="new-password" value={v.password} onChange={set("password")} />
          </Field>
          {s.password_saved ? <label className="check"><input type="checkbox" checked={v.clear_password} onChange={set("clear_password")} /> Remove the saved password</label> : null}
        </div>
        <div className="row fields">
          <Field label="Sender address"><input type="email" maxLength={254} value={v.from_address} onChange={set("from_address")} placeholder="billing@example.org" /></Field>
          <Field label="Sender name"><input maxLength={120} value={v.from_name} onChange={set("from_name")} /></Field>
          <Field label="Reply-to (optional)"><input type="email" maxLength={254} value={v.reply_to} onChange={set("reply_to")} /></Field>
        </div>
        <div className="actions left"><button className="primary" type="submit">Save</button>{saved ? <span role="status" className="muted">Saved.</span> : null}</div>
      </form>
      <div className="row">
        <Field label="Send a test email to"><input type="email" maxLength={254} value={testTo} onChange={(e) => setTestTo(e.target.value)} /></Field>
        <button type="button" disabled={!testTo || !s.ready} onClick={sendTest}>Send test</button>
      </div>
      {test ? <div className={`alert ${test.status === "SENT" ? "info" : "warn"}`} role="status">{test.status === "SENT" ? `Test email sent to ${test.to}.` : `Not sent: ${test.error}`}</div> : null}
    </section>
  );
}

const split = (t: string) => t.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);

/** The Send email form: To (the customer's address to start with), Cc, subject and message, all editable; one click
 * sends one email. `url` posts it; `extra` is added to the body (a statement's customer and period). */
export function SendEmail({ title, defaults, url, extra, attachment, onClose, onSent }: {
  title: string; defaults: any; url: string; extra?: Record<string, any>; attachment: string; onClose: () => void; onSent: (log: any) => void;
}) {
  const [v, setV] = useState({ to: (defaults.to || []).join(", "), cc: "", subject: defaults.subject || "", message: defaults.message || "" });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try { onSent(await api.post(url, { ...extra, to: split(v.to), cc: split(v.cc), subject: v.subject, message: v.message })); }
    catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Modal title={title} onClose={onClose} wide>
      <form onSubmit={submit}>
        <ErrorBox error={err} />
        {!defaults.ready ? <div className="alert warn" role="note">Email isn't set up yet: an Administrator sets the mail server in System/About → Settings.</div> : null}
        <Field label="To" hint="Separate several addresses with commas."><input required value={v.to} onChange={(e) => setV({ ...v, to: e.target.value })} /></Field>
        <Field label="Cc (optional)"><input value={v.cc} onChange={(e) => setV({ ...v, cc: e.target.value })} /></Field>
        <Field label="Subject"><input required maxLength={200} value={v.subject} onChange={(e) => setV({ ...v, subject: e.target.value })} /></Field>
        <Field label="Message"><textarea rows={6} maxLength={10000} value={v.message} onChange={(e) => setV({ ...v, message: e.target.value })} /></Field>
        <p className="hint">Attached: {attachment}</p>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit" disabled={busy || !defaults.ready}>{busy ? "Sending…" : "Send email"}</button></div>
      </form>
    </Modal>
  );
}

export function EmailLog({ rows }: { rows: any[] }) {
  if (!rows.length) return null;
  return (
    <section className="card" aria-labelledby="email-log-h" data-testid="email-log">
      <h2 id="email-log-h">Emails</h2>
      <table className="table"><thead><tr><th>Sent</th><th>To</th><th>Subject</th><th>By</th><th>Result</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id}><td>{String(r.sent_at).slice(0, 16).replace("T", " ")}</td><td>{r.to}{r.cc ? <span className="muted"> (cc {r.cc})</span> : null}</td><td>{r.subject}</td><td>{r.sent_by}</td>
          <td>{r.status === "SENT" ? "Sent" : <span className="badge red" title={r.error || ""}>Failed</span>}</td></tr>)}</tbody></table>
    </section>
  );
}
