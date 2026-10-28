// 1.10.0 (#58): the update notification - the indicator in the top bar, the "What's new" dialog with the notes of
// every newer release, the banner (server: Administrators, every page; local: My account), and the Administrator's
// on/off setting. The release information is fetched by the backend; the browser only talks to PennyWarden.
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { ErrorBox, Modal } from "../components";

export type UpdateStatus = {
  enabled: boolean; channel: string | null; mode: string; available: boolean; checked_at: string | null; error: boolean;
  current: { version: string; build: number | null };
  latest: Rel | null; download_url: string | null; releases: Rel[];
};
type Rel = { version: string; build: number | null; channel: string; date: string; url: string; notes: string };

export const label = (r: { version: string; build: number | null }) => (r.build ? `${r.version} (test build ${r.build})` : r.version);
const SAFE_LINK = /^https:\/\/(github\.com|pennywarden\.org)\//;

/** Inline formatting of release notes: **bold**, `code` and [text](https link) - everything else stays text.
 * Builds React elements only; nothing in the notes is ever parsed as HTML. */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined) out.push(<b key={m.index}>{m[1]}</b>);
    else if (m[2] !== undefined) out.push(<code key={m.index}>{m[2]}</code>);
    else if (SAFE_LINK.test(m[4])) out.push(<a key={m.index} href={m[4]} target="_blank" rel="noopener noreferrer">{m[3]}</a>);
    else out.push(m[3]);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Release notes (the CHANGELOG section: paragraphs, "- " bullets with wrapped lines, headings) as React elements. */
export function ReleaseNotes({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let para: string[] = [];
  let items: string[] = [];
  const flush = () => {
    if (para.length) { blocks.push(<p key={`p${blocks.length}`}>{inline(para.join(" "))}</p>); para = []; }
    if (items.length) { blocks.push(<ul key={`u${blocks.length}`}>{items.map((x, i) => <li key={i}>{inline(x)}</li>)}</ul>); items = []; }
  };
  for (const raw of (text || "").split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { flush(); continue; }
    const h = /^#{1,6}\s+(.*)$/.exec(line);
    const li = /^\s*[-*]\s+(.*)$/.exec(line);
    if (h) { flush(); blocks.push(<h4 key={`h${blocks.length}`}>{inline(h[1])}</h4>); }
    else if (li) { if (para.length) flush(); items.push(li[1]); }
    else if (items.length && /^\s+/.test(raw)) items[items.length - 1] += " " + line.trim();   // a wrapped bullet
    else { if (items.length) flush(); para.push(line.trim()); }
  }
  flush();
  return <div className="release-notes">{blocks}</div>;
}

export function WhatsNew({ s, onClose }: { s: UpdateStatus; onClose: () => void }) {
  return (
    <Modal title={`PennyWarden ${s.latest ? label(s.latest) : ""} is available`} onClose={onClose} wide>
      <p>You have <b>{label(s.current)}</b>. {s.releases.length > 1 ? `Here is what changed in the ${s.releases.length} newer releases, newest first.` : "Here is what changed."}</p>
      <div className="whats-new" data-testid="whats-new">
        {s.releases.map((r) => (
          <Fragment key={`${r.version}-${r.build ?? ""}`}>
            <h3>{label(r)} <span className="muted">· {r.date}</span></h3>
            <ReleaseNotes text={r.notes} />
          </Fragment>
        ))}
      </div>
      <p className="hint">Updating is done by you: download the new version and install it as before (on a server, run the
        installer command). Your data is kept.</p>
      <div className="actions">
        <button type="button" onClick={onClose}>Close</button>
        {s.download_url ? <a className="button primary" href={s.download_url} target="_blank" rel="noopener noreferrer">Open the download page</a> : null}
      </div>
    </Modal>
  );
}

/** Loads the update status once per sign-in (it changes at most once a day). */
export function useUpdates(): UpdateStatus | null {
  const [s, setS] = useState<UpdateStatus | null>(null);
  useEffect(() => { api.get("/api/updates").then(setS, () => setS(null)); }, []);
  return s;
}

/** Top bar: a gold circle with an up arrow cut out of it (the coin's gold), left of the user's name. */
export function UpdateIndicator({ s }: { s: UpdateStatus | null }) {
  const [open, setOpen] = useState(false);
  if (!s?.available || !s.latest) return null;
  return (
    <>
      <button type="button" className="update-dot" onClick={() => setOpen(true)} title={`PennyWarden ${label(s.latest)} is available`}
              aria-label={`Update available: PennyWarden ${label(s.latest)}`} data-testid="update-indicator">
        <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
          <defs>
            <mask id="update-arrow-cut">
              <rect width="20" height="20" fill="#fff" />
              <path d="M10 4.5 L15 10 H11.7 V15.5 H8.3 V10 H5 Z" fill="#000" />
            </mask>
          </defs>
          <circle cx="10" cy="10" r="9.5" fill="#f2b632" mask="url(#update-arrow-cut)" />
        </svg>
      </button>
      {open ? <WhatsNew s={s} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

export function UpdateBanner({ s }: { s: UpdateStatus | null }) {
  const [open, setOpen] = useState(false);
  if (!s?.available || !s.latest) return null;
  return (
    <div className="alert info banner update-banner" role="status" data-testid="update-banner">
      <b>PennyWarden {label(s.latest)} is available</b> (released {s.latest.date}; you have {label(s.current)}).{" "}
      <button type="button" className="link" onClick={() => setOpen(true)}>What's new</button>
      {s.download_url ? <> · <a href={s.download_url} target="_blank" rel="noopener noreferrer">Download</a></> : null}
      {open ? <WhatsNew s={s} onClose={() => setOpen(false)} /> : null}
    </div>
  );
}

/** System/About (Administrators): turn the check on or off, see when it last ran, check now. */
/** The Administrator's on/off switch and Check now; 2.2.0 (#349) `readOnly` for the other roles: whether the check is
 * on, when it last ran and its result, with the release notes - no switch, no Check now. */
export function UpdateSettings({ readOnly = false }: { readOnly?: boolean }) {
  const [s, setS] = useState<UpdateStatus | null>(null);
  const [notes, setNotes] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/updates").then(setS, () => setS(null)); }, []);
  if (!s) return null;
  const toggle = async (enabled: boolean) => {
    const before = s;
    setS({ ...s, enabled }); // shown at once; put back if saving fails
    setBusy(true); setErr(null);
    try { setS(await api.put("/api/updates/settings", { enabled })); } catch (x) { setS(before); setErr(x); } finally { setBusy(false); }
  };
  // A failed request (session expired, server error) is shown; the last known status stays on screen.
  const now = async () => {
    setBusy(true); setErr(null);
    try { setS(await api.post("/api/updates/check")); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <section className="card" aria-labelledby="upd-h">
      <h2 id="upd-h">Update check</h2>
      <ErrorBox error={err} />
      {readOnly
        ? <p data-testid="update-check-status">Checking for new versions: <b>{s.enabled ? "On" : "Off"}</b> <span className="muted">(set by an Administrator)</span></p>
        : <label className="check"><input type="checkbox" checked={s.enabled} disabled={busy} onChange={(e) => toggle(e.target.checked)} /> Check for new versions of PennyWarden</label>}
      <p className="hint">About once a day PennyWarden asks pennywarden.org for the list of releases and shows a gold arrow next to each user's name when a newer one is available. Nothing about your organization is sent. Turned off, no request is made.</p>
      {!s.channel ? <p className="hint">This build ({s.current.version}) was not built for release, so it does not check.</p> : (
        <p>
          {s.channel === "test" ? "Test build: looks for newer test builds and releases. " : "Looks for new releases. "}
          {s.checked_at ? <>Last checked {new Date(s.checked_at).toLocaleString()}{s.error ? " — pennywarden.org could not be reached" : ""}. </> : "Not checked yet. "}
          {s.available && s.latest ? <b>{label(s.latest)} is available. </b> : s.checked_at && !s.error ? "You have the newest version. " : null}
          {s.enabled && !readOnly ? <button type="button" className="small" disabled={busy} onClick={now}>Check now</button> : null}
          {s.available && s.latest ? <button type="button" className="small" onClick={() => setNotes(true)}>What's new</button> : null}
        </p>
      )}
      {notes ? <WhatsNew s={s} onClose={() => setNotes(false)} /> : null}
    </section>
  );
}
