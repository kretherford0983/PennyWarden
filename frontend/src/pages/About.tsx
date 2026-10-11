import { useEffect, useState } from "react";
import { api } from "../api";
import { BuildDetails, ErrorBox, Loading } from "../components";
import { BackupRestore } from "./BackupRestore";
import { UpdateSettings } from "./Updates";

export default function About() {
  const [a, setA] = useState<any>(null);
  useEffect(() => {
    api.get("/api/system/about").then(setA);
  }, []);
  if (!a) return <Loading />;
  return (
    <div>
      <h1>System / About</h1>
      <BuildDetails info={a} />
      {a.bind_host ? <dl className="dl"><dt>Bind address</dt><dd>{a.bind_host}:{a.port}</dd></dl> : null}
      {a.insecure_transport_warning ? <div className="alert warn">Network deployment without HTTPS configuration is not secure.</div> : null}
      <div className="alert warn" role="note"><strong>Data protection:</strong> {a.backup_notice}</div>
      {a.restore_max_mb != null ? <UpdateSettings /> : null}
      {a.restore_max_mb != null ? <ModulesPanel /> : null}
      {a.restore_max_mb != null ? <BackupRestore maxMb={a.restore_max_mb} /> : null}
    </div>
  );
}

/** v1.6.0 CR-033: optional modules, switched on/off by an Administrator (data is kept when a module is off). */
function ModulesPanel() {
  const [m, setM] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.get("/api/system/modules").then(setM, setErr); }, []);
  const toggle = async (key: "fundraisers" | "checks", on: boolean) => {
    setErr(null);
    setSaved(false);
    const before = m;
    setM({ ...m, [key]: on }); // shown at once; reverted if saving fails
    try { setM(await api.put("/api/system/modules", { [key]: on })); setSaved(true); } catch (x) { setM(before); setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="modules-h">
      <h2 id="modules-h">Optional modules</h2>
      <ErrorBox error={err} />
      {m ? (
        <>
          <label className="check"><input type="checkbox" checked={m.fundraisers} onChange={(e) => toggle("fundraisers", e.target.checked)} /> Fundraiser module</label>
          <p className="hint">Adds <b>Fundraisers</b> to the menu of Budget Managers, Budget Users, Register Users and Auditors (it appears at their next sign-in or page reload).
            Turning it off hides the module; fundraisers that were set up are kept.</p>
          <label className="check"><input type="checkbox" checked={!!m.checks} onChange={(e) => toggle("checks", e.target.checked)} /> Payments module</label>
          <p className="hint">Check printing, payments, cover letters and envelopes. Adds <b>Payments Setup</b> to the Administrator's menu (check styles,
            signatures, letter and envelope templates, test prints), and <b>Payments</b> and a <b>Print check</b> action on withdrawals for Register Users. For
            printable check stock that already carries the bank numbers. Turning it off hides the module; settings are kept.</p>
          {saved ? <p className="hint" role="status">Saved.</p> : null}
        </>
      ) : null}
    </section>
  );
}
