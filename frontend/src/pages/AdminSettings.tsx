/** 2.0.0 (#126): System/About - the organization name, the effective settings (with the server settings editor on
 * server installs) and the backup age warning. The server validates everything; this is convenience only. */
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, Modal, useConfirmable } from "../components";

export function OrganizationPanel({ name, onRenamed }: { name: string; onRenamed: (n: string) => void }) {
  const [v, setV] = useState(name);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const save = async () => {
    setErr(null); setSaved(false);
    try { const r = await api.put("/api/system/organization", { name: v }); setV(r.name); setSaved(true); onRenamed(r.name); } catch (x) { setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="org-h">
      <h2 id="org-h">Organization</h2>
      <ErrorBox error={err} />
      <div className="row form-row">
        <Field label="Organization name"><input maxLength={120} value={v} onChange={(e) => { setV(e.target.value); setSaved(false); }} /></Field>
        <button onClick={save} disabled={!v.trim() || v.trim() === name}>Rename</button>
      </div>
      <p className="hint">Used in new reports, signature pages, letters and backup file names. Documents already made keep the name they were made with.</p>
      {saved ? <p className="hint" role="status">Saved.</p> : null}
    </section>
  );
}

type Row = {
  name: string; label: string; value: any; source: string; editable: boolean; locked: boolean; read_only_reason: string | null;
  restart_required: boolean; saved_value: any; choices: string[] | null; range: [number, number] | null; type: "bool" | "int" | "text";
};

const show = (v: any) => (Array.isArray(v) ? (v.length ? v.join(", ") : "—") : typeof v === "boolean" ? (v ? "On" : "Off") : v === "" || v == null ? "—" : String(v));

export function SettingsPanel() {
  const [d, setD] = useState<any>(null);
  const [edit, setEdit] = useState<Record<string, any>>({});
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState<string[] | null>(null);
  const [askPw, setAskPw] = useState(false);
  const [pw, setPw] = useState("");
  const { run, dialog } = useConfirmable();
  const load = () => api.get("/api/system/settings").then(setD, setErr);
  useEffect(() => { load(); }, []);
  if (!d) return <ErrorBox error={err} />;
  const rows: Row[] = d.settings;
  const changes = Object.fromEntries(Object.entries(edit).filter(([k, v]) => {
    const r = rows.find((x) => x.name === k);
    return r && v !== r.saved_value;
  }));
  const dirty = Object.keys(changes).length > 0;
  const submit = async (password?: string) => {
    setErr(null); setSaved(null);
    try {
      const r = await run((confirmations) => api.put("/api/system/settings", { changes, confirmations, password }));
      if (r) { setD(r); setEdit({}); setSaved(r.changed); setAskPw(false); setPw(""); }
    } catch (x) { setErr(x); }
  };
  const save = () => ("trusted_proxies" in changes ? setAskPw(true) : submit());
  const input = (r: Row) => {
    const v = r.name in edit ? edit[r.name] : r.saved_value;
    const set = (x: any) => setEdit({ ...edit, [r.name]: x });
    if (r.type === "bool") return <input type="checkbox" aria-label={r.label} checked={!!v} onChange={(e) => set(e.target.checked)} />;
    if (r.choices) return <select aria-label={r.label} value={v} onChange={(e) => set(e.target.value)}>{r.choices.map((c) => <option key={c} value={c}>{c}</option>)}</select>;
    if (r.type === "int") return <input type="number" aria-label={r.label} min={r.range?.[0]} max={r.range?.[1]} value={v} onChange={(e) => set(e.target.value === "" ? "" : Number(e.target.value))} style={{ width: "8em" }} />;
    return <input aria-label={r.label} maxLength={1000} value={v ?? ""} placeholder="none" onChange={(e) => set(e.target.value)} />;
  };
  return (
    <section className="card" aria-labelledby="settings-h">
      <h2 id="settings-h">Settings</h2>
      <p className="hint">
        Every setting in effect and where it comes from: the built-in <b>default</b>, <code>{d.config_file}</code> in the data folder, an
        <b> environment</b> variable (FM_…) or a <b>command line</b> option — each one overrides the one before.
        {d.editor ? " Settings marked editable are saved to config.toml and take effect when the service is restarted. A setting set by the environment or the command line can only be changed there." :
          d.mode === "server" ? "" : " On a local install, change settings in config.toml (docs/configuration.md)."}
      </p>
      {d.restart_required ? <div className="alert warn" role="status" data-testid="restart-required"><strong>Restart required:</strong> saved changes take effect when the PennyWarden service is restarted.</div> : null}
      <ErrorBox error={err} />
      <table className="table compact settings-table">
        <thead><tr><th>Setting</th><th>In effect</th><th>Source</th>{d.editor ? <th>Change</th> : null}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td>{r.label}</td>
              <td>{show(r.value)}{r.restart_required ? <span className="badge" title={`Saved: ${show(r.saved_value)}`}> restart required</span> : null}</td>
              <td>{r.source}</td>
              {d.editor ? <td>{r.editable ? input(r) : <span className="muted">{r.read_only_reason || "Read-only"}</span>}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
      {d.editor ? (
        <div className="actions left">
          <button className="primary" onClick={save} disabled={!dirty}>Save settings</button>
          <button onClick={() => setEdit({})} disabled={!dirty}>Undo changes</button>
          {saved ? <span className="hint" role="status">{saved.length ? `Saved: ${saved.length} setting(s).` : "Nothing changed."}</span> : null}
        </div>
      ) : null}
      {askPw ? (
        <Modal title="Confirm with your password" onClose={() => setAskPw(false)}>
          <p>Trusted proxies decide which client addresses the application believes. Enter your password to change them.</p>
          <ErrorBox error={err} />
          <Field label="Your password"><input type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus /></Field>
          <div className="actions"><button onClick={() => setAskPw(false)}>Cancel</button><button className="primary" disabled={!pw} onClick={() => submit(pw)}>Save settings</button></div>
        </Modal>
      ) : null}
      {dialog}
    </section>
  );
}

export function BackupWarningSetting() {
  const [a, setA] = useState<any>(null);
  const [days, setDays] = useState<number | "">("");
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.get("/api/system/backup-age").then((x) => { setA(x); setDays(x.warning_days); }, setErr); }, []);
  const save = async () => {
    setErr(null); setSaved(false);
    try { const x = await api.put("/api/system/backup-age", { days: days === "" ? -1 : days }); setA(x); setDays(x.warning_days); setSaved(true); } catch (e) { setErr(e); }
  };
  if (!a) return <ErrorBox error={err} />;
  return (
    <div className="backup-warning-setting">
      <ErrorBox error={err} />
      <div className="row form-row">
        <Field label="Warn when there is no backup for (days, 0 = never)">
          <input type="number" min={0} max={365} value={days} onChange={(e) => { setDays(e.target.value === "" ? "" : Number(e.target.value)); setSaved(false); }} style={{ width: "7em" }} />
        </Field>
        <button onClick={save} disabled={days === a.warning_days}>Save</button>
      </div>
      <p className="hint">Administrators see a warning at the top of every page once no backup (made here or scheduled) has been made for this many days.
        {a.last_backup_at ? ` Last backup: ${new Date(a.last_backup_at).toLocaleString()}.` : " No backup has been made on this installation yet."}</p>
      {saved ? <p className="hint" role="status">Saved.</p> : null}
    </div>
  );
}

/** 2.0.0 (#127): who is signed in (Administrators; Auditors view only) and ending sessions. */
export function SessionsPanel() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => api.get("/api/system/sessions").then(setD, setErr);
  useEffect(() => { load(); }, []);
  const act = async (fn: () => Promise<any>, done: (n: number) => string) => {
    setErr(null); setMsg(null);
    try { const r = await fn(); setMsg(done(r.ended)); await load(); } catch (x) { setErr(x); }
  };
  const when = (iso: string) => new Date(iso).toLocaleString();
  return (
    <section className="card" aria-labelledby="sessions-h">
      <h2 id="sessions-h">Signed-in sessions</h2>
      <p className="hint">Everyone signed in now, with when they signed in, their last activity and the address their last request came from.
        {d?.can_end ? " Ending a session signs that person out at their next click; they can sign in again (reset the password or disable the account in Users if it may be misused)." : ""}</p>
      <ErrorBox error={err} />
      {msg ? <p className="hint" role="status">{msg}</p> : null}
      {d ? (
        <>
          <table className="table compact">
            <thead><tr><th>User</th><th>Signed in</th><th>Last activity</th><th>Address</th>{d.can_end ? <th /> : null}</tr></thead>
            <tbody>
              {d.sessions.map((s: any) => (
                <tr key={s.ref}>
                  <td>{s.display_name || s.username} <span className="muted">{s.username}</span>{s.current ? <span className="badge"> you, this session</span> : null}{s.signing_in ? <span className="badge grey"> signing in</span> : null}</td>
                  <td>{when(s.signed_in_at)}</td><td>{when(s.last_activity_at)}</td><td>{s.client_ip || "—"}</td>
                  {d.can_end ? (
                    <td className="actions-cell">
                      {!s.current ? <button className="small" onClick={() => act(() => api.post(`/api/system/sessions/${s.ref}/end`, {}), () => `Session of ${s.username} ended.`)}>End session</button> : null}{" "}
                      {d.sessions.filter((x: any) => x.user_id === s.user_id && !x.current).length > 1 ?
                        <button className="small" onClick={() => act(() => api.post("/api/system/sessions/end-user", { user_id: s.user_id }), (n) => `${n} session(s) of ${s.username} ended.`)}>End all of {s.username}</button> : null}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
          {d.can_end && d.sessions.some((s: any) => !s.current) ? (
            <div className="actions left">
              <button onClick={() => window.confirm("End every session except yours? Everyone else must sign in again.") && act(() => api.post("/api/system/sessions/end-all", {}), (n) => `${n} session(s) ended. Everyone else must sign in again.`)}>End all other sessions</button>
              <button onClick={load}>Refresh</button>
            </div>
          ) : <div className="actions left"><button onClick={load}>Refresh</button></div>}
        </>
      ) : null}
    </section>
  );
}

/** 2.0.0 (#128): a sanitized diagnostics file for troubleshooting (Administrators). */
export function DiagnosticsPanel() {
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const download = async () => {
    setErr(null); setBusy(true); setDone(false);
    try {
      const blob = await api.postBlob("/api/system/diagnostics", {});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pennywarden-diagnostics-${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "")}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      setDone(true);
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <section className="card" aria-labelledby="diag-h">
      <h2 id="diag-h">Diagnostics</h2>
      <p className="hint">A file to help with troubleshooting: version and build, operating system, settings, database and attachment sizes, free disk
        space, the database version and the last 1,000 log lines. Passwords, keys, session identifiers, amounts, account numbers and email
        addresses are left out or replaced. Nothing is sent anywhere: you decide whom to give the file to. Each download is recorded in the audit log.</p>
      <ErrorBox error={err} />
      <div className="actions left">
        <button onClick={download} disabled={busy}>{busy ? "Preparing…" : "Download diagnostics"}</button>
        {done ? <span className="hint" role="status">Downloaded.</span> : null}
      </div>
    </section>
  );
}

const size = (b: number | null | undefined) => (b == null ? "—" : b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(1)} GB` : b >= 1024 ** 2 ? `${(b / 1024 ** 2).toFixed(1)} MB` : `${Math.ceil(b / 1024)} KB`);

/** 2.0.0 (#129): database and storage health (Administrators). */
export function HealthPanel() {
  const [h, setH] = useState<any>(null);
  const [chk, setChk] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/api/system/health-check").then(setH, setErr);
  useEffect(() => { load(); }, []);
  const run = async () => {
    setErr(null); setBusy(true);
    try { setChk(await api.post("/api/system/health-check/integrity", {})); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <section className="card" aria-labelledby="health-h">
      <h2 id="health-h">Health</h2>
      <ErrorBox error={err} />
      {h ? (
        <>
          {h.low_disk ? <div className="alert warn" role="alert">{h.low_disk_message}</div> : null}
          <dl className="dl">
            <dt>Database</dt><dd>{size(h.database_bytes)}</dd>
            <dt>Attachments</dt><dd>{size(h.attachments_bytes)} ({h.attachment_files} files)</dd>
            <dt>Free disk space</dt><dd>{size(h.disk.free)}{h.disk.free_percent != null ? ` (${h.disk.free_percent} %)` : ""}{h.low_disk ? " – low" : ""}</dd>
            <dt>Database version</dt><dd>{h.migrations.current || "—"} {h.migrations.up_to_date ? <span className="badge">up to date</span> : <span className="badge grey">expected {h.migrations.head}</span>}</dd>
          </dl>
          <p className="hint">A warning appears here and at the top of every page for Administrators when less than 1 GB or 10 % of the disk is free.</p>
        </>
      ) : null}
      <div className="actions left">
        <button onClick={run} disabled={busy}>{busy ? "Checking…" : "Run integrity check"}</button>
        <button onClick={load}>Refresh</button>
      </div>
      {chk ? <div className={`alert ${chk.ok ? "ok" : "error"}`} role="status">{chk.message} <span className="muted">({chk.seconds} s)</span></div> : null}
      <p className="hint">The integrity check reads the whole database to make sure it is not damaged. It is safe while people are working; on a large
        database it can take a minute. Each check is recorded in the audit log.</p>
    </section>
  );
}
