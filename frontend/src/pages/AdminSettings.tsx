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
