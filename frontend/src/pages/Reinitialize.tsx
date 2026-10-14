/** 2.0.0 (#125): reinitialize (keeping users) - System/About → Advanced tab → Reinitialize, and the banner after it. */
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, Field, GuardedForm } from "../components";
import { poll, Steps } from "./BackupRestore";

/** Collapsed by default; the form exists only while it is open. Build 13: titled "Reinitialize" (it sits on the Advanced
 * tab, so "Advanced" read twice), with no second heading inside. */
export function ReinitializePanel() {
  const [open, setOpen] = useState(false);
  return (
    <details className="card advanced" data-testid="reinitialize" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary><h2 style={{ display: "inline" }}>Reinitialize</h2></summary>
      {open ? <Reinitialize /> : null}
    </details>
  );
}

function Reinitialize() {
  const [info, setInfo] = useState<any>(null);
  const [f, setF] = useState({ confirm: "", password: "", code: "", passphrase: "", passphrase_confirmation: "" });
  const [own, setOwn] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [job, setJob] = useState<any>(null);
  useEffect(() => { api.get("/api/system/reinitialize").then(setInfo, setErr); }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const body: any = { confirm: f.confirm, password: f.password };
      if (info?.code_required) body.code = f.code;
      if (own) { body.passphrase = f.passphrase; body.passphrase_confirmation = f.passphrase_confirmation; }
      const j = await api.post("/api/system/reinitialize", body);
      setJob(j);
      setF({ confirm: "", password: "", code: "", passphrase: "", passphrase_confirmation: "" });
      await poll(`/api/system/reinitialize/jobs/${j.id}`, setJob);
    } catch (x) { setErr(x); }
  };
  if (!info) return <ErrorBox error={err} />;
  const running = job?.state === "running";
  return (
    <section aria-label="Reinitialize (keep the users)">
      <div className="alert error" role="note">
        <strong>This removes all financial data:</strong> {info.removed.join(", ")}. Currently {info.counts.transactions} transactions,{" "}
        {info.counts.fiscal_years} Fiscal Years, {info.counts.entities} entities, {info.counts.bank_accounts} bank accounts and {info.counts.attachments} attachments.
        <div><strong>Kept:</strong> {info.kept.join(", ")}.</div>
      </div>
      <p className="hint">A safety backup is made first and checked; if that fails, nothing is removed. It is kept in the server's <code>pre-reinitialize/</code> folder
        (it can't be downloaded here), and the server's owner can always restore it with <code>pennywarden restore … --use-server-key</code>. Everyone else
        is signed out, and everyone sees a notice after signing in until an Administrator acknowledges it. It can be done once in 24 hours from here.</p>
      {info.cooldown_until ? <div className="alert warn">Reinitialized less than 24 hours ago: possible again after {new Date(info.cooldown_until).toLocaleString()}.</div> : null}
      <ErrorBox error={err} />
      {!running && job?.state !== "done" && !info.cooldown_until ? (
        <GuardedForm onSubmit={submit}>
          <label className="check"><input type="checkbox" checked={own} onChange={(e) => setOwn(e.target.checked)} /> Use my own passphrase for the safety backup (so it can also be restored from this page)</label>
          {own ? (
            <div className="row fields">
              <Field label="Backup passphrase" hint="At least 12 characters."><input type="password" minLength={12} required autoComplete="new-password" value={f.passphrase} onChange={(e) => setF({ ...f, passphrase: e.target.value })} /></Field>
              <Field label="Repeat the passphrase"><input type="password" minLength={12} required autoComplete="new-password" value={f.passphrase_confirmation} onChange={(e) => setF({ ...f, passphrase_confirmation: e.target.value })} /></Field>
            </div>
          ) : null}
          <Field label={`Type "${info.confirm_word}" to confirm`}><input autoComplete="off" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} /></Field>
          <Field label="Your password"><input type="password" required autoComplete="current-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
          {info.code_required ? <Field label="Two-step verification code"><input inputMode="numeric" autoComplete="one-time-code" required value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field> : null}
          <div className="actions left"><button className="danger" type="submit" disabled={f.confirm.trim() !== info.confirm_word || !f.password}>Reinitialize</button></div>
        </GuardedForm>
      ) : null}
      <Steps job={job} />
      {job?.state === "failed" ? <div className="alert error" role="alert">{job.error}</div> : null}
      {job?.state === "done" ? (
        <div className="alert ok" role="status" data-testid="reinit-done">
          Reinitialized. Safety backup: <b>{job.result.filename}</b> in <code>{job.result.folder}</code>.
          <div>To undo, the server's owner stops the service and runs: <code>{job.result.restore_command}</code></div>
        </div>
      ) : null}
    </section>
  );
}

/** Shown to every signed-in user after a reinitialize until an Administrator acknowledges it. */
export function ReinitializedBanner({ path }: { path: string }) {
  const [b, setB] = useState<any>(null);
  useEffect(() => { api.get("/api/system/reinitialized").then(setB, () => setB(null)); }, [path]);
  if (!b?.show) return null;
  const ack = async () => { try { setB(await api.post("/api/system/reinitialized/acknowledge", {})); } catch { /* shown again next page */ } };
  return (
    <div className="alert warn banner" role="alert" data-testid="reinitialized-banner">
      The data was reinitialized by {b.by} on {new Date(b.at).toLocaleString()}: all financial data before then was removed (a safety backup was kept).
      {b.can_acknowledge ? <> <button className="small" onClick={ack}>Acknowledge for everyone</button></> : null}
    </div>
  );
}
