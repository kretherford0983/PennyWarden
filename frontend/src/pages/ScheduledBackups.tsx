// 1.9.0 (#62): scheduled automatic backups (System/About → Backup / Restore → Scheduled).
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, Field, GuardedForm, Loading } from "../components";
import { Link } from "../router";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const size = (n: number | null) => (n == null ? "" : n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);
const TRIGGER: Record<string, string> = { SCHEDULED: "Scheduled", RETRY: "Retry", MISSED: "Missed (at start)", RUN_NOW: "Run now" };

export default function ScheduledBackups() {
  const [d, setD] = useState<any>(null);
  const [f, setF] = useState<any>(null);
  const [pp, setPp] = useState({ change: false, passphrase: "", passphrase_confirmation: "", password: "" });
  const [err, setErr] = useState<unknown>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = () => api.get("/api/system/backup-schedule").then((j) => {
    setD(j);
    setF({ enabled: j.enabled, frequency: j.frequency, weekday: j.weekday, time_of_day: j.time_of_day,
      destination: j.destination || (j.allowed_folders?.[0] ?? ""), keep_daily: j.keep_daily, keep_weekly: j.keep_weekly, keep_monthly: j.keep_monthly });
    return j;
  }, setErr);
  useEffect(() => { load(); }, []);
  if (!d || !f) return <><ErrorBox error={err} /><Loading /></>;
  const needPp = !d.passphrase_set || pp.change;
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null); setMsg(null);
    try {
      const body: any = { ...f, weekday: Number(f.weekday), keep_daily: Number(f.keep_daily), keep_weekly: Number(f.keep_weekly), keep_monthly: Number(f.keep_monthly) };
      if (needPp && pp.passphrase) Object.assign(body, { passphrase: pp.passphrase, passphrase_confirmation: pp.passphrase_confirmation, password: pp.password });
      await api.put("/api/system/backup-schedule", body);
      setPp({ change: false, passphrase: "", passphrase_confirmation: "", password: "" });
      await load();
      setMsg({ ok: true, text: "Saved." });
    } catch (x) { setErr(x); }
  };
  const test = async () => {
    setErr(null); setMsg(null);
    try {
      const r = await api.post("/api/system/backup-schedule/test", { destination: f.destination });
      setMsg({ ok: r.ok, text: r.message });
    } catch (x) { setErr(x); }
  };
  const runNow = async () => {
    setErr(null); setMsg(null);
    try {
      await api.post("/api/system/backup-schedule/run");
      setMsg({ ok: true, text: "Backup started — it appears in the history below when it is done." });
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const j = await load();
        if (j?.history?.[0] && j.history[0].result !== "RUNNING") break;
      }
    } catch (x) { setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="sched-h">
      <h2 id="sched-h">Scheduled backups</h2>
      <p>PennyWarden writes an encrypted backup to a folder on its own, on a schedule, and keeps the number of backups you
        choose. The folder must be one this computer can already see — a local folder, an external drive or a mounted
        network share. Copying backups offsite is done outside PennyWarden. The download backup is unchanged.</p>
      {d.alert?.failed ? <div className="alert error" role="alert">{d.alert.message}</div> : null}
      <ErrorBox error={err} />
      {msg ? <div className={`alert ${msg.ok ? "ok" : "error"}`} role="status">{msg.text}</div> : null}
      <GuardedForm onSubmit={save}>
        <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /> Back up automatically</label>
        <div className="row fields">
          <Field label="Schedule">
            <select aria-label="Schedule" value={f.frequency} onChange={(e) => setF({ ...f, frequency: e.target.value })}>
              <option value="DAILY">Daily</option><option value="WEEKLY">Weekly</option>
            </select>
          </Field>
          {f.frequency === "WEEKLY" ? (
            <Field label="Day">
              <select aria-label="Day" value={f.weekday} onChange={(e) => setF({ ...f, weekday: Number(e.target.value) })}>
                {DAYS.map((x, i) => <option key={x} value={i}>{x}</option>)}
              </select>
            </Field>
          ) : null}
          <Field label="Time" hint={`This computer's time${d.timezone ? ` (${d.timezone})` : ""}.`}>
            <input type="time" aria-label="Time" required value={f.time_of_day} onChange={(e) => setF({ ...f, time_of_day: e.target.value })} />
          </Field>
        </div>
        <div className="row fields">
          {d.mode === "server" ? (
            <Field label="Backup folder" hint="The folders the server owner listed in config.toml (backup_folders).">
              {d.allowed_folders?.length ? (
                <select aria-label="Backup folder" value={f.destination} onChange={(e) => setF({ ...f, destination: e.target.value })}>
                  {d.allowed_folders.map((x: string) => <option key={x} value={x}>{x}</option>)}
                </select>
              ) : <p className="alert warn">No backup folders are configured on this server. Ask the server owner to list them as <code>backup_folders</code> in config.toml.</p>}
            </Field>
          ) : (
            <Field label="Backup folder" hint="The full path, e.g. D:\PennyWarden-backups or /Volumes/Backup/PennyWarden.">
              <input aria-label="Backup folder" value={f.destination} onChange={(e) => setF({ ...f, destination: e.target.value })} />
            </Field>
          )}
          <div className="test-folder"><button type="button" onClick={test} disabled={!f.destination}>Test</button></div>
        </div>
        <fieldset className="keep">
          <legend>Keep</legend>
          <div className="row fields">
            {f.frequency === "DAILY" ? <Field label="Daily backups"><input type="number" aria-label="Daily backups" min={0} max={366} value={f.keep_daily} onChange={(e) => setF({ ...f, keep_daily: e.target.value })} /></Field> : null}
            <Field label="Weekly backups" hint="The first backup of each week."><input type="number" aria-label="Weekly backups" min={0} max={366} value={f.keep_weekly} onChange={(e) => setF({ ...f, keep_weekly: e.target.value })} /></Field>
            <Field label="Monthly backups" hint="The first backup of each month."><input type="number" aria-label="Monthly backups" min={0} max={366} value={f.keep_monthly} onChange={(e) => setF({ ...f, keep_monthly: e.target.value })} /></Field>
          </div>
          <p className="hint">Older backups are deleted automatically. Only backup files PennyWarden wrote are ever deleted — never anything else in the folder.</p>
        </fieldset>
        <fieldset className="keep">
          <legend>Backup passphrase</legend>
          {d.passphrase_set && !pp.change ? (
            <p>Set on {String(d.passphrase_set_at).slice(0, 10)}. <button type="button" className="link" onClick={() => setPp({ ...pp, change: true })}>Change passphrase</button></p>
          ) : (
            <>
              <div className="alert warn" role="note"><b>Remember this passphrase.</b> Restoring a scheduled backup needs it, and nobody can recover a forgotten one. After a change, the backups made before still need the earlier passphrase.</div>
              <div className="row fields">
                <Field label="Backup passphrase" hint="At least 12 characters."><input type="password" aria-label="Backup passphrase" minLength={12} autoComplete="new-password" value={pp.passphrase} onChange={(e) => setPp({ ...pp, passphrase: e.target.value })} /></Field>
                <Field label="Repeat the passphrase"><input type="password" aria-label="Repeat the passphrase" minLength={12} autoComplete="new-password" value={pp.passphrase_confirmation} onChange={(e) => setPp({ ...pp, passphrase_confirmation: e.target.value })} /></Field>
              </div>
              <Field label="Your password" hint="Confirms that it is you."><input type="password" aria-label="Your password" autoComplete="current-password" value={pp.password} onChange={(e) => setPp({ ...pp, password: e.target.value })} /></Field>
              {pp.change ? <button type="button" className="link" onClick={() => setPp({ change: false, passphrase: "", passphrase_confirmation: "", password: "" })}>Keep the current passphrase</button> : null}
            </>
          )}
        </fieldset>
        <div className="actions left">
          <button className="primary" type="submit">Save</button>
          <button type="button" onClick={runNow} disabled={!d.passphrase_set || !d.destination}>Run now</button>
        </div>
      </GuardedForm>
      {d.enabled && d.next_run_local ? <p data-testid="next-backup">Next backup: <b>{d.next_run_local}</b>{d.retry_local ? <> · retry at <b>{d.retry_local}</b></> : null}</p> : null}
      <h3>Recent backups</h3>
      {d.history.length ? (
        <div className="table-wrap">
          <table className="table" aria-label="Backup history">
            <thead><tr><th>Started</th><th>How</th><th>Result</th><th>File</th><th className="num">Size</th><th title="Which keep rule holds on to this backup, with the current keep settings">Kept as</th></tr></thead>
            <tbody>
              {d.history.map((h: any) => (
                <tr key={h.id}>
                  <td>{h.started_local}</td><td>{TRIGGER[h.trigger] || h.trigger}</td>
                  <td>{h.result === "SUCCESS" ? <span className="badge green">Done</span> : h.result === "FAILED" ? <span className="badge red">Failed</span> : <span className="badge grey">Running</span>}{h.error ? <div className="muted">{h.error}</div> : null}</td>
                  <td>{h.filename}{h.deleted ? <span className="muted"> (removed by the keep rules)</span> : null}</td>
                  <td className="num">{size(h.size)}</td>
                  <td data-testid="kept-as">{keptAs(h.kept_as)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">No scheduled backups yet.</p>}
    </section>
  );
}

/** 2.1.0 (#233): why a backup is still there - computed by the server with the same rules as retention. */
function keptAs(k: string | null | undefined) {
  if (!k) return null;
  if (k === "Removed") return <span className="muted">Removed</span>;
  if (k === "Removed at the next backup") return <span className="badge yellow" title="The keep settings changed: the next backup removes it">{k}</span>;
  if (k.startsWith("Not managed")) return <span className="muted" title="Made into another folder; the keep rules only manage the current folder">{k}</span>;
  return <span className="badge green">{k}</span>;
}

/** Administrators: shown at the top of every page while the last scheduled backup has failed. */
export function BackupFailedBanner({ path }: { path: string }) {
  const [a, setA] = useState<any>(null);
  useEffect(() => { api.get("/api/system/backup-schedule/alert").then(setA, () => setA(null)); }, [path]);
  if (!a?.failed && !a?.stale && !a?.low_disk) return null;
  return (
    <>
      {a.failed ? <div className="alert error banner" role="alert" data-testid="backup-failed-banner">{a.message} <Link to="/about/backups">Backup settings</Link></div> : null}
      {/* 2.0.0 (#126): no backup for the set number of days */}
      {a.stale && !a.failed ? <div className="alert warn banner" role="alert" data-testid="backup-age-banner">{a.stale_message} <Link to="/about/backups">Backup / Restore</Link></div> : null}
      {/* 2.0.0 (#129): low disk space on the data folder's volume */}
      {a.low_disk ? <div className="alert warn banner" role="alert" data-testid="low-disk-banner">{a.low_disk_message} <Link to="/about/health">System health</Link></div> : null}
    </>
  );
}
