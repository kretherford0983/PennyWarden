/** 2.0.0 (#130): maintenance mode - the notice everyone sees, and the Administrator's switch on System/About. */
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field } from "../components";

type M = { on: boolean; active: boolean; scheduled?: boolean; message?: string; starts_at?: string | null; set_by?: string };

const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");

/** The message as plain text (never HTML), with when it starts if it is scheduled. */
export function MaintenanceNotice({ m, banner = false }: { m: M; banner?: boolean }) {
  return (
    <div className={`alert warn${banner ? " banner" : ""}`} role="status" data-testid="maintenance-notice">
      <strong>{m.active ? "Maintenance: changes are paused." : `Maintenance starts ${when(m.starts_at)}.`}</strong>{" "}
      <span className="pre-line">{m.message}</span>
      {m.active ? " You can still look things up." : ""}
    </div>
  );
}

/** For every signed-in user: shown from the moment maintenance is scheduled until it is turned off. */
export function MaintenanceBanner({ path }: { path: string }) {
  const [m, setM] = useState<M | null>(null);
  useEffect(() => {
    const load = () => api.get("/api/system/status").then((s) => setM(s.maintenance_mode || null), () => undefined);
    load();
    window.addEventListener("pw:maintenance-changed", load);
    return () => window.removeEventListener("pw:maintenance-changed", load);
  }, [path]);
  if (!m?.on) return null;
  return <MaintenanceNotice m={m} banner />;
}

export function MaintenancePanel() {
  const [m, setM] = useState<M | null>(null);
  const [msg, setMsg] = useState("");
  const [start, setStart] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const load = () => api.get("/api/system/maintenance").then((x) => { setM(x); if (x.message) setMsg(x.message); }, setErr);
  useEffect(() => { load(); }, []);
  const set = async (on: boolean) => {
    setErr(null);
    try {
      const body: any = { on };
      if (on) { body.message = msg; body.starts_at = start ? new Date(start).toISOString() : null; }
      const r = await api.put("/api/system/maintenance", body);
      setM(r); setStart("");
      window.dispatchEvent(new CustomEvent("pw:maintenance-changed"));
    } catch (x) { setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="maint-h">
      <h2 id="maint-h">Maintenance mode</h2>
      <p className="hint">While it is on, everyone can sign in and look things up, but only Administrators can change anything. Everyone sees your message —
        from the moment you schedule it. Restores already pause the application on their own.</p>
      <ErrorBox error={err} />
      {m?.on ? <MaintenanceNotice m={m} /> : null}
      <Field label="Message for the users">
        <textarea maxLength={500} rows={2} value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="e.g. Year-end close: please don't enter transactions until Monday." />
      </Field>
      <div className="row form-row">
        <Field label="Start (optional; empty = now)"><input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
      </div>
      <div className="actions left">
        <button className="primary" onClick={() => set(true)} disabled={!msg.trim()}>{m?.on ? "Update" : start ? "Schedule maintenance" : "Turn on maintenance mode"}</button>
        {m?.on ? <button onClick={() => set(false)}>Turn off</button> : null}
      </div>
    </section>
  );
}
