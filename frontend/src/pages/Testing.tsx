// 2.2.0 (#231): testing mode - the every-page banner and System/About -> Testing (Administrators). Testing mode is
// turned on only in config.toml; the Testing endpoints don't exist without it.
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading } from "../components";

export function TestingBanner() {
  return (
    <div className="alert testing-banner banner" role="note" data-testid="testing-banner">
      <b>TESTING MODE</b> — test data only. This server is set up for trying things out; don't enter real records.
    </div>
  );
}

const local = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : "—");
const toInput = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

export function TestingPanel() {
  const [v, setV] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [next, setNext] = useState(toInput(new Date(Date.now() + 5 * 60000)));
  const [last, setLast] = useState(toInput(new Date(Date.now() - 10 * 86400000)));
  const [days, setDays] = useState<Record<number, string>>({});
  const [due, setDue] = useState<Record<number, string>>({});
  const load = () => api.get("/api/system/testing").then(setV, setErr);
  useEffect(() => { load(); }, []);
  const act = async (url: string, body: any, done: string) => {
    setErr(null); setOk(null);
    try { setV(await api.post(url, body)); setOk(done); } catch (x) { setErr(x); }
  };
  if (!v) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  return (
    <section className="card testing-panel" aria-labelledby="testing-h">
      <h2 id="testing-h">Testing</h2>
      <p>Move timers and schedules instead of waiting for them. Nothing here changes financial records, and the real
        clock is not moved (transaction dates, the audit log, sessions and two-step codes keep the real time). Every
        action is recorded in the audit log as a testing action.</p>
      <ErrorBox error={err} />
      {ok ? <div className="alert ok" role="status">{ok}</div> : null}

      <h3>Scheduled backups</h3>
      <dl className="dl">
        <dt>Next scheduled backup</dt><dd>{v.schedule.enabled ? local(v.schedule.next_run_at) : "scheduled backups are off"}</dd>
        <dt>Retry of a failed backup</dt><dd>{v.schedule.retry_at ? local(v.schedule.retry_at) : "none waiting"}</dd>
      </dl>
      <div className="row fields">
        <Field label="Next scheduled backup at"><input type="datetime-local" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <div className="actions left">
          <button type="button" disabled={!v.schedule.enabled} onClick={() => act("/api/system/testing/backup-schedule", { next_run_at: new Date(next).toISOString() }, "Next scheduled backup moved.")}>Set</button>
          <button type="button" disabled={!v.schedule.enabled} onClick={() => act("/api/system/testing/backup-schedule", { due_now: true }, "The scheduled backup is due now: it runs within a minute.")}>Run as if due now</button>
          <button type="button" disabled={!v.schedule.retry_at} onClick={() => act("/api/system/testing/backup-retry", {}, "The retry is due now: it runs within a minute.")}>Retry the failed backup now</button>
        </div>
      </div>
      {v.runs.length ? (
        <>
          <p className="hint">Retention keeps daily, weekly and monthly backups by when each run started. Move runs back in time to see what it keeps and removes at the next scheduled backup.</p>
          <table className="table compact" aria-label="Backup runs">
            <thead><tr><th>Started</th><th>Result</th><th>File</th><th>Move back</th></tr></thead>
            <tbody>{v.runs.map((r: any) => (
              <tr key={r.id}>
                <td>{local(r.started_at)}</td><td>{r.result}{r.removed ? " (removed)" : ""}</td><td>{r.filename || ""}</td>
                <td><span className="row-buttons">
                  <input aria-label={`Days to move run ${r.id} back`} type="number" min={1} max={3660} style={{ width: "5em" }} value={days[r.id] ?? "1"} onChange={(e) => setDays({ ...days, [r.id]: e.target.value })} />
                  <button type="button" className="small" onClick={() => act(`/api/system/testing/backup-runs/${r.id}/backdate`, { days: Number(days[r.id] ?? "1") }, "Backup run moved back.")}>days back</button>
                </span></td>
              </tr>
            ))}</tbody>
          </table>
        </>
      ) : null}

      <h3>Backup reminder</h3>
      <p>Last successful backup: <b>{local(v.last_backup_at)}</b>{v.last_backup_overridden ? " (set here)" : ""}. {v.backup_age?.stale ? "The no-backup warning is showing." : "No warning."}</p>
      <div className="row fields">
        <Field label="Last successful backup at"><input type="datetime-local" value={last} onChange={(e) => setLast(e.target.value)} /></Field>
        <div className="actions left">
          <button type="button" onClick={() => act("/api/system/testing/last-backup", { last_backup_at: new Date(last).toISOString() }, "Last backup time set.")}>Set</button>
          <button type="button" disabled={!v.last_backup_overridden} onClick={() => act("/api/system/testing/last-backup", { last_backup_at: null }, "Back to the real last backup.")}>Use the real time</button>
        </div>
      </div>

      <h3>Reinitialize</h3>
      <p>{v.reinitialize_cooldown_until ? <>Reinitialize is possible again after {local(v.reinitialize_cooldown_until)}. </> : "No cooldown. "}
        <button type="button" disabled={!v.reinitialize_cooldown_until} onClick={() => act("/api/system/testing/reinitialize-cooldown/clear", {}, "Cooldown cleared.")}>Clear the cooldown</button></p>

      <h3>Organization reminders</h3>
      {v.reminders.length ? (
        <table className="table compact" aria-label="Reminders to move">
          <thead><tr><th>Reminder</th><th>Due</th><th>New due date</th></tr></thead>
          <tbody>{v.reminders.map((r: any) => (
            <tr key={r.id}>
              <td>{r.title}{r.repeats ? <span className="muted"> (repeats)</span> : null}</td><td>{r.due_date}</td>
              <td><span className="row-buttons">
                <input type="date" aria-label={`New due date for ${r.title}`} value={due[r.id] ?? r.due_date} onChange={(e) => setDue({ ...due, [r.id]: e.target.value })} />
                <button type="button" className="small" onClick={() => act(`/api/system/testing/reminders/${r.id}/due-date`, { due_date: due[r.id] ?? r.due_date }, "Reminder moved.")}>Move</button>
              </span></td>
            </tr>
          ))}</tbody>
        </table>
      ) : <p className="muted">No open organization reminders.</p>}

      <h3>Update check</h3>
      <p>Last checked: {local(v.update_check?.checked_at)}. <button type="button" onClick={() => act("/api/system/testing/update-check", {}, "Update check done.")}>Check for updates now</button></p>
    </section>
  );
}
