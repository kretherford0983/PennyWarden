// 2.4.0 polish (#503): the Logo choice every printing place shares - the organization logo (System/About -> General
// -> Organization logos), this place's own upload, or none (the default). The choice is part of the editor's settings
// (saved with Save); an own logo is uploaded / removed at once, and uploading switches the choice to "Its own logo".
import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { ErrorBox, Field } from "./components";
import { Link } from "./router";

export type LogoSource = "ORG" | "OWN" | "NONE" | "FOLLOW";

let orgCache: Promise<any> | null = null;
/** The organization's logos (Administrators); refreshed after a change on the Organization logos panel. */
export function loadOrgLogos(fresh = false): Promise<any> {
  if (fresh || !orgCache) orgCache = api.get("/api/system/organization/logos").catch(() => ({ logos: {} }));
  return orgCache;
}

export function useOrgLogo(slot = "full") {
  const [info, setInfo] = useState<any>(undefined);
  useEffect(() => {
    let on = true;
    loadOrgLogos().then((x) => { if (on) setInfo(x?.logos?.[slot] ?? null); });
    const again = () => loadOrgLogos().then((x) => { if (on) setInfo(x?.logos?.[slot] ?? null); });
    window.addEventListener("pw:org-logos-changed", again);
    return () => { on = false; window.removeEventListener("pw:org-logos-changed", again); };
  }, [slot]);
  return info;
}

export function OrgLogoThumb({ slot = "full", info }: { slot?: string; info: any }) {
  return info ? <img className="logo-thumb" src={`/api/system/organization/logos/${slot}?v=${info.version}`} alt="The organization logo" />
    : <p className="alert warn" role="note">No organization logo yet. Add one under <Link to="/about/general">System/About → General → Organization logos</Link>; until then nothing prints here.</p>;
}

export function LogoChoice({ id, source, onSource, own, ownSrc, onUpload, onRemove, uploadNote, followLabel, sizeHint, slot = "full",
  children }: {
  id: string;
  source: LogoSource;
  onSource: (s: LogoSource) => void;
  own: any;                                  // this place's own logo (null when none)
  ownSrc?: string;                           // its image address
  onUpload?: (f: File) => Promise<void>;     // undefined: can't upload yet (an unsaved template)
  onRemove?: () => Promise<void>;
  uploadNote?: string;
  followLabel?: string;                      // offers "follow" (the year-end statement follows the receipt)
  sizeHint: string;
  slot?: string;
  children?: ReactNode;                      // position and other settings, shown when a logo prints
}) {
  const org = useOrgLogo(slot);
  const [err, setErr] = useState<unknown>(null);
  const act = async (fn: () => Promise<void>) => { setErr(null); try { await fn(); } catch (x) { setErr(x); } };
  return (
    <div className="logo-choice" data-testid={`logo-choice-${id}`}>
      <ErrorBox error={err} />
      <div className="row form-row">
        <Field label="Logo"><select id={`${id}-logo-source`} value={source} onChange={(ev) => onSource(ev.target.value as LogoSource)}>
          {followLabel ? <option value="FOLLOW">{followLabel}</option> : null}
          <option value="ORG">Organization logo</option>
          <option value="OWN">Its own logo</option>
          <option value="NONE">No logo</option>
        </select></Field>
        {source !== "NONE" && source !== "FOLLOW" ? children : null}
      </div>
      {source === "ORG" ? (
        <div className="row form-row">{org === undefined ? null : <OrgLogoThumb slot={slot} info={org} />}
          {org ? <p className="hint">Changes to the organization logo show here too.</p> : null}</div>
      ) : null}
      {source === "OWN" ? (
        <div className="row form-row">
          {own && ownSrc ? <img className="logo-thumb" src={ownSrc} alt="This logo" /> : <p className="muted">No logo of its own yet.</p>}
          {own && onRemove ? <button type="button" className="small" onClick={() => act(async () => { await onRemove(); onSource("NONE"); })}>Remove logo</button> : null}
          {onUpload ? <label className="button small">{own ? "Replace logo…" : "Add a logo…"}
            <input type="file" accept="image/png,image/jpeg" hidden aria-label={`${id} logo image`} onChange={(ev) => {
              const f = ev.target.files?.[0];
              ev.target.value = "";
              if (f) act(async () => { await onUpload(f); onSource("OWN"); });
            }} />
          </label> : <p className="hint">{uploadNote || "Save first, then add the logo here."}</p>}
        </div>
      ) : null}
      <p className="hint">{sizeHint}</p>
    </div>
  );
}
