import { useEffect, useState, type FormEvent } from "react";
import { api, preAuthCsrf } from "../api";
import { ErrorBox, Field, GuardedForm } from "../components";
import { RestorePanel } from "./BackupRestore";

export default function InitWizard({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ workspace_name: "", admin_username: "", admin_email: "", admin_first_name: "", admin_last_name: "", password: "", password_confirmation: "" });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [restore, setRestore] = useState(false); // v1.4.1 CR-024
  useEffect(() => {
    preAuthCsrf();
  }, []);
  const set = (k: keyof typeof f) => (e: any) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (f.password !== f.password_confirmation) {
      setErr(new Error("Password and confirmation do not match."));
      return;
    }
    setBusy(true);
    try {
      await api.post("/api/system/initialize", f);
      onDone();
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(false);
    }
  };
  if (restore)
    return (
      <div className="center">
        <div className="card auth-card wide-auth">
          <RestorePanel wizard />
          <p><button type="button" className="linklike" onClick={() => setRestore(false)}>Back to creating a new organization</button></p>
        </div>
      </div>
    );
  return (
    <div className="center">
      <GuardedForm className="card auth-card" onSubmit={submit} aria-labelledby="init-title">
        <h1 id="init-title">Initialization Wizard</h1>
        <p className="muted">This installation has not been initialized. Create the Workspace and the initial Administrator. No default credentials exist.</p>
        <ErrorBox error={err} />
        <Field label="Organization / Workspace Name"><input required maxLength={120} value={f.workspace_name} onChange={set("workspace_name")} /></Field>
        <div className="row fields">
          <Field label="Administrator First Name"><input required maxLength={60} autoComplete="given-name" value={f.admin_first_name} onChange={set("admin_first_name")} /></Field>
          <Field label="Administrator Last Name"><input required maxLength={60} autoComplete="family-name" value={f.admin_last_name} onChange={set("admin_last_name")} /></Field>
        </div>
        <Field label="Administrator Username"><input required minLength={3} maxLength={64} autoComplete="username" value={f.admin_username} onChange={set("admin_username")} /></Field>
        <Field label="Administrator Email Address"><input required type="email" maxLength={254} value={f.admin_email} onChange={set("admin_email")} /></Field>
        <Field label="Password" hint="At least 12 characters including a letter and a digit.">
          <input required type="password" minLength={12} autoComplete="new-password" value={f.password} onChange={set("password")} />
        </Field>
        <Field label="Password Confirmation"><input required type="password" autoComplete="new-password" value={f.password_confirmation} onChange={set("password_confirmation")} /></Field>
        <p className="hint">The POC does not provide backup/restore. Protect the application data directory (database, attachments and secrets) yourself.</p>
        <button className="primary" disabled={busy} type="submit">Initialize</button>
        <p className="hint">Moving an existing installation? <button type="button" className="linklike" onClick={() => setRestore(true)}>Restore from a backup instead</button></p>
      </GuardedForm>
    </div>
  );
}
