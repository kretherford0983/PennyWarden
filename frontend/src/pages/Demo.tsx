// 2.2.0 (#243): the demo banner - on every page and on the sign-in page. Reset demo data works without signing in
// (a locked-out evaluator can always recover); Remove the demo is for the demo Administrator.
import { useState } from "react";
import { api, preAuthCsrf } from "../api";
import { ErrorBox, Field, GuardedForm, Modal } from "../components";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Waits until the pause for the swap is over, then reloads the application. */
async function waitAndReload() {
  await sleep(800);
  for (let i = 0; i < 120; i++) {
    try {
      const s = await api.get("/api/system/status");
      if (!s.maintenance) break;
    } catch { /* the database is being swapped */ }
    await sleep(500);
  }
  window.location.assign("/");
}

export function DemoBanner({ canRemove = false, signIn = false }: { canRemove?: boolean; signIn?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [remove, setRemove] = useState(false);
  const reset = async () => {
    setErr(null); setBusy(true);
    try {
      if (signIn) await preAuthCsrf();
      await api.post("/api/system/demo/reset");
      await waitAndReload();
    } catch (x) { setErr(x); setBusy(false); }
  };
  return (
    <div className="alert demo-banner banner" role="note" data-testid="demo-banner">
      <b>DEMO</b> — sample data; changes are discarded when PennyWarden restarts.{" "}
      <button type="button" className="small" disabled={busy} onClick={reset}>{busy ? "Resetting…" : "Reset demo data"}</button>{" "}
      {canRemove
        ? <button type="button" className="small" onClick={() => setRemove(true)}>Remove the demo and start fresh</button>
        : <a href="https://github.com/kretherford0983/PennyWarden/blob/main/docs/demo.md" target="_blank" rel="noopener">Remove the demo and start fresh</a>}
      <ErrorBox error={err} />
      {remove ? <RemoveDemo onClose={() => setRemove(false)} /> : null}
    </div>
  );
}

function RemoveDemo({ onClose }: { onClose: () => void }) {
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async () => {
    setErr(null);
    try {
      await api.post("/api/system/demo/remove", { confirm });
      await waitAndReload();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Remove the demo" onClose={onClose}>
      <GuardedForm onSubmit={(e) => { e.preventDefault(); return submit(); }}>
        <ErrorBox error={err} />
        <p>This removes the demo organization, its users, attachments, audit log and its published encryption key. Your settings file (<code>config.toml</code>) stays. Next comes the Initialization Wizard, exactly as on a new install, with a new encryption key. Nothing of the demo remains.</p>
        <Field label="Type REMOVE to confirm"><input required autoComplete="off" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary danger" type="submit" disabled={confirm !== "REMOVE"}>Remove the demo</button></div>
      </GuardedForm>
    </Modal>
  );
}
