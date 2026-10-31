/** 2.2.0 (#280): System/About -> Branding (Administrators). The organization's look for generated reports and
 * presentations: a palette (a ready-made one, or a custom Material 3 palette generated from a primary and a secondary
 * color and then adjusted), a full logo and a small mark, and one line of footer text. Checks, cover letters, receipts
 * and envelopes are not affected. The server validates everything again; the checks here are for the live preview.
 * 2.3.0 (#386) dual branding: a light and a dark theme, each a ready-made palette or custom colors - any role or chart
 * color can be changed directly and the palette then shows as Custom - the theme each type of output uses (PDF reports,
 * presentations) and optional logos for dark backgrounds. */
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading, useConfirmable } from "../components";
import { contrast, deltaE, generate, isHex, ROLES, type Role } from "../palette";

type Preset = { id: string; label: string; source_primary: string; source_secondary: string; colors: Record<Role, string>; series: string[] };

function ColorInput({ label, value, onChange, id }: { label: string; value: string; onChange: (v: string) => void; id: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <div className="field">
      <span className="field-label" aria-hidden="true">{label}</span>
      <div className="color-input">
      <input type="color" aria-label={`${label} (picker)`} value={isHex(value) ? value : "#000000"} onChange={(e) => onChange(e.target.value)} />
      <input id={id} aria-label={label} className="hex" maxLength={7} value={text} aria-invalid={isHex(text) ? undefined : true}
             onChange={(e) => { setText(e.target.value); if (isHex(e.target.value)) onChange(e.target.value.toLowerCase()); }} />
      </div>
    </div>
  );
}

function Swatches({ colors, series }: { colors: Record<string, string>; series: string[] }) {
  return (
    <span className="swatches" aria-hidden="true">
      {[colors.primary, colors.secondary, colors.primary_container, ...series.slice(0, 4)].map((c, i) => <span key={i} style={{ background: c }} />)}
    </span>
  );
}

function Preview({ colors, series, footer, logos, org, dark }: { colors: Record<string, string>; series: string[]; footer: string; logos: any; org: string; dark: boolean }) {
  const bars = [["Golf Outing", 80], ["Raffle", 45], ["Gala", 62], ["Bake sale", 20]] as const;
  const page = dark ? colors.surface : "#ffffff";
  const full = dark && logos.useDark && logos.dark_full ? "dark_full" : "full";
  const mark = dark && logos.useDark && logos.dark_mark ? "dark_mark" : "mark";
  return (
    <div className="brand-preview" data-testid={dark ? "branding-preview-dark" : "branding-preview"} style={{ color: colors.on_surface, background: page }}
         aria-label={`Live preview of the ${dark ? "dark" : "light"} theme`}>
      <div className="bp-head">
        <div>
          <div className="bp-title" style={{ color: colors.primary }}>{dark ? "Fundraising presentation" : "Fundraising report"}</div>
          <div className="bp-sub" style={{ color: colors.on_surface_variant }}>{org}</div>
        </div>
        {logos[full] ? <img src={`/api/system/branding/logo/${full}?v=${logos[full].sha256}`} alt="Full logo" /> : null}
      </div>
      <div className="bp-band" style={{ background: colors.primary, color: colors.on_primary }}>Highlights</div>
      <div className="bp-tile" style={{ background: colors.primary_container, color: colors.on_primary_container, borderColor: colors.outline_variant }}>
        Net proceeds <b>$12,450.00</b>
      </div>
      <table className="bp-table" style={{ borderColor: colors.outline }}>
        <thead><tr style={{ background: colors.surface_variant }}><th>Fundraiser</th><th>Net</th></tr></thead>
        <tbody>
          {bars.map(([n, v], i) => <tr key={n} style={{ background: i % 2 ? colors.surface : page }}><td>{n}</td><td>${(v * 100).toLocaleString("en-US")}.00</td></tr>)}
        </tbody>
      </table>
      <div className="bp-chart" role="img" aria-label="Sample chart: each bar is labeled">
        {bars.map(([n, v], i) => (
          <div key={n} className="bp-bar-row">
            <span className="bp-bar-label">{n}</span>
            <span className="bp-bar" style={{ width: `${v}%`, background: series[i % series.length] }} />
            <span className="bp-bar-value">${(v * 100).toLocaleString("en-US")}</span>
          </div>
        ))}
      </div>
      <div className="bp-foot" style={{ color: colors.on_surface_variant, borderColor: colors.outline_variant }}>
        {logos[mark] ? <img src={`/api/system/branding/logo/${mark}?v=${logos[mark].sha256}`} alt="Small mark" /> : null}
        <span>{footer || "Fundraising report"}</span><span>Page 1 of 3</span>
      </div>
    </div>
  );
}

function LogoSlot({ slot, info, label, hint, onChanged }: { slot: "full" | "mark" | "dark_full" | "dark_mark"; info: any; label: string; hint: string; onChanged: (v: any) => void }) {
  const [err, setErr] = useState<unknown>(null);
  const act = async (fn: () => Promise<any>) => { setErr(null); try { onChanged(await fn()); } catch (x) { setErr(x); } };
  return (
    <fieldset className="lines">
      <legend>{label}</legend>
      <ErrorBox error={err} />
      {info ? (
        <div className="row form-row">
          <img className="logo-thumb" src={`/api/system/branding/logo/${slot}?v=${info.sha256}`} alt={label} />
          <span className="muted">{info.width} × {info.height} px</span>
          <button type="button" className="small" onClick={() => act(() => api.post(`/api/system/branding/logo/${slot}/remove`, {}))}>Remove</button>
        </div>
      ) : <p className="muted">None.</p>}
      <label className="button small">{info ? "Replace…" : "Add…"}
        <input type="file" accept="image/png,image/jpeg" hidden aria-label={`${label} image`} onChange={(ev) => {
          const f = ev.target.files?.[0];
          ev.target.value = "";
          if (f) act(() => api.upload(`/api/system/branding/logo/${slot}`, f));
        }} />
      </label>
      <p className="hint">{hint}</p>
    </fieldset>
  );
}

type Pal = { preset: string; colors: Record<Role, string>; series: string[] };

/** One theme's palette editor (#386): the ready-made palettes, Generate from the two colors, and every color role and
 * chart color editable directly - a change makes the palette Custom. */
function ThemeEditor({ which, pal, setPal, presets, src, setSrc, v, onTouched }: {
  which: "light" | "dark"; pal: Pal; setPal: (p: Pal) => void; presets: Preset[]; src: { primary: string; secondary: string };
  setSrc: (x: { primary: string; secondary: string }) => void; v: any; onTouched: () => void;
}) {
  const dark = which === "dark";
  const roleLabel = (r: string) => (r === "white" ? "white paper" : v.roles.find((x: any) => x.id === r)?.label || r);
  const choose = (id: string) => {
    onTouched();
    const p = presets.find((x) => x.id === id);
    if (p) setPal({ preset: id, colors: p.colors, series: p.series });
  };
  const edit = (next: Partial<Pal>) => { onTouched(); setPal({ ...pal, ...next, preset: "custom" }); };
  const regenerate = () => {
    if (!isHex(src.primary) || !isHex(src.secondary)) return;
    const g = generate(src.primary, src.secondary, dark);
    edit({ colors: g.colors, series: g.series });
  };
  const name = `brand-preset-${which}`;
  return (
    <>
      <fieldset className="lines">
        <legend>{dark ? "Dark palette" : "Light palette"}</legend>
        <div className="preset-list" role="radiogroup" aria-label={dark ? "Dark palette" : "Palette"}>
          {presets.map((p) => (
            <label key={p.id} className="check preset">
              <input type="radio" name={name} checked={pal.preset === p.id} onChange={() => choose(p.id)} />
              <Swatches colors={p.colors} series={p.series} /> {p.label}{p.id === "pennywarden" ? " (default)" : ""}
            </label>
          ))}
          <label className="check preset">
            <input type="radio" name={name} checked={pal.preset === "custom"} onChange={() => edit({})} /> Custom
          </label>
        </div>
        <p className="hint">Change any color below and the palette becomes <i>Custom</i>.</p>
      </fieldset>
      <fieldset className="lines">
        <legend>{dark ? "Generate the dark palette" : "Generate a palette"}</legend>
        <div className="row form-row">
          <ColorInput id={`src-primary-${which}`} label="Primary color" value={src.primary} onChange={(x) => setSrc({ ...src, primary: x })} />
          <ColorInput id={`src-secondary-${which}`} label="Secondary color" value={src.secondary} onChange={(x) => setSrc({ ...src, secondary: x })} />
          <button type="button" onClick={regenerate} disabled={!isHex(src.primary) || !isHex(src.secondary)}>
            {dark ? "Generate dark palette" : "Generate recommended palette"}</button>
        </div>
        <p className="hint">{dark ? "The Material 3 dark scheme from the same two colors as the light palette (for slides on a dark background)."
          : "Generates a Material 3 palette (color roles and chart colors) from your two colors."} Then adjust any color below.</p>
      </fieldset>
      <details>
        <summary>Color roles</summary>
        <div className="role-grid">
          {ROLES.map((r) => <ColorInput key={r} id={`role-${which}-${r}`} label={roleLabel(r)} value={pal.colors[r]} onChange={(x) => edit({ colors: { ...pal.colors, [r]: x } })} />)}
        </div>
      </details>
      <details>
        <summary>Chart series colors</summary>
        <div className="role-grid">
          {pal.series.map((c, i) => <ColorInput key={i} id={`series-${which}-${i}`} label={`Series ${i + 1}`} value={c} onChange={(x) => { const s = [...pal.series]; s[i] = x; edit({ series: s }); }} />)}
        </div>
      </details>
    </>
  );
}

function useChecks(v: any, pal: Pal | null, dark: boolean) {
  const checks = useMemo(() => (!v || !pal ? [] : ((dark ? v.dark_contrast_pairs : v.contrast_pairs) as [Role, string][]).map(([fg, bg]) => {
    const b = bg === "white" ? "#ffffff" : pal.colors[bg as Role];
    const r = pal.colors[fg] && b ? contrast(pal.colors[fg], b) : 0;
    return { fg, bg, ratio: r, ok: r >= v.minimum_contrast };
  })), [v, pal, dark]);
  const similar = useMemo(() => {
    const out: [number, number][] = [];
    const s = pal?.series || [];
    for (let i = 0; i < s.length; i++) for (let j = i + 1; j < s.length; j++) if (v && deltaE(s[i], s[j]) < v.similar_delta_e) out.push([i, j]);
    return out;
  }, [pal, v]);
  return { checks, similar };
}

export function BrandingPanel({ org }: { org: string }) {
  const [v, setV] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [light, setLight] = useState<Pal | null>(null);
  const [dark, setDark] = useState<Pal | null>(null);
  const [tab, setTab] = useState<"light" | "dark">("light");
  const [src, setSrc] = useState({ primary: "#1f3a5f", secondary: "#d4a017" });
  const [footer, setFooter] = useState("");
  const [themes, setThemes] = useState<Record<string, string>>({});
  const [darkLogos, setDarkLogos] = useState(false);
  const [saved, setSaved] = useState(false);
  const { run, dialog } = useConfirmable();
  const take = (d: any) => {
    setV(d);
    setLight({ preset: d.preset, colors: d.colors, series: d.series });
    setDark({ preset: d.dark.preset, colors: d.dark.colors, series: d.dark.series });
    setFooter(d.footer_text || ""); setThemes(d.themes); setDarkLogos(!!d.dark_logos);
    setSrc({ primary: d.source_primary || d.colors.primary, secondary: d.source_secondary || d.colors.secondary });
  };
  useEffect(() => { api.get("/api/system/branding").then(take, setErr); }, []);
  const lc = useChecks(v, light, false);
  const dc = useChecks(v, dark, true);
  if (!v || !light || !dark) return err ? <ErrorBox error={err} /> : <Loading />;
  const roleLabel = (r: string) => (r === "white" ? "white paper" : r === "surface" && tab === "dark" ? "the dark background" : v.roles.find((x: any) => x.id === r)?.label || r);
  const touched = () => setSaved(false);
  const presets: Preset[] = v.presets || [];
  const darkPresets: Preset[] = (v.dark_presets || []).map((p: any) => ({ ...p, source_primary: "", source_secondary: "" }));
  const cur = tab === "dark" ? dc : lc;
  const bad = lc.checks.some((c) => !c.ok) || dc.checks.some((c) => !c.ok);
  const save = async () => {
    setErr(null); setSaved(false);
    try {
      const r = await run((confirmations) => api.put("/api/system/branding", {
        preset: light.preset, footer_text: footer || null, confirmations,
        ...(light.preset === "custom" ? { source_primary: src.primary, source_secondary: src.secondary, colors: light.colors, series: light.series } : {}),
        dark_preset: dark.preset, ...(dark.preset === "custom" ? { dark_colors: dark.colors, dark_series: dark.series } : {}),
        themes, dark_logos: darkLogos,
      }));
      if (r) { take(r); setSaved(true); }
    } catch (x) { setErr(x); }
  };
  const reset = async () => {
    setErr(null); setSaved(false);
    try { take(await api.post("/api/system/branding/reset", {})); setSaved(true); } catch (x) { setErr(x); }
  };
  const logosChanged = (d: any) => setV((c: any) => ({ ...c, logos: d.logos }));
  const pal = tab === "dark" ? dark : light;
  return (
    <section className="card" aria-labelledby="brand-h">
      <h2 id="brand-h">Organization branding</h2>
      <p className="hint">Your colors and logo on generated reports and presentations: every PDF report, the fundraiser report and deck, the
        Fiscal Year fundraising report and deck, and the Quarterly / Annual report and deck. Checks, cover letters, receipts and envelopes keep their own design.</p>
      <ErrorBox error={err} />
      <fieldset className="lines" data-testid="branding-outputs">
        <legend>Theme for each type of output</legend>
        <div className="row form-row">
          {v.outputs.map((o: any) => (
            <Field key={o.id} label={o.label}>
              <select aria-label={`Theme for ${o.label}`} value={themes[o.id]} onChange={(e) => { setThemes({ ...themes, [o.id]: e.target.value }); touched(); }}>
                <option value="LIGHT">Light</option><option value="DARK">Dark</option>
              </select>
            </Field>
          ))}
        </div>
        <p className="hint">Printed reports suit the light theme (white paper); a presentation shown on a screen can use the dark one. Word documents always use the light theme.</p>
      </fieldset>
      <div role="tablist" className="row" aria-label="Theme">
        <button role="tab" type="button" aria-selected={tab === "light"} className={tab === "light" ? "primary" : ""} onClick={() => setTab("light")}>Light theme</button>
        <button role="tab" type="button" aria-selected={tab === "dark"} className={tab === "dark" ? "primary" : ""} onClick={() => setTab("dark")}>Dark theme</button>
      </div>
      <div className="brand-layout">
        <div>
          {tab === "light"
            ? <ThemeEditor key="light" which="light" pal={light} setPal={setLight} presets={presets} src={src} setSrc={setSrc} v={v} onTouched={touched} />
            : <ThemeEditor key="dark" which="dark" pal={dark} setPal={setDark} presets={darkPresets} src={src} setSrc={setSrc} v={v} onTouched={touched} />}
          <div className="contrast-list" data-testid="branding-contrast">
            {cur.checks.filter((c) => !c.ok).map((c) => (
              <div key={`${c.fg}-${c.bg}`} className="alert error" role="alert">
                {roleLabel(c.fg)} on {roleLabel(c.bg)}: contrast {c.ratio.toFixed(2)}:1 — text needs at least {v.minimum_contrast}:1 (WCAG AA). It can't be saved like this.
              </div>
            ))}
            {cur.checks.length && cur.checks.every((c) => c.ok) ? <p className="hint ok">✓ Every text color of the {tab} theme meets WCAG AA contrast.</p> : null}
            {(tab === "light" ? dc : lc).checks.some((c) => !c.ok) ? <div className="alert error" role="alert">The {tab === "light" ? "dark" : "light"} theme has a text color below WCAG AA contrast: open it to fix it before saving.</div> : null}
            {cur.similar.length ? <div className="alert warn" role="note">Chart series colors {cur.similar.slice(0, 4).map(([i, j]) => `${i + 1} and ${j + 1}`).join(", ")} are hard to tell apart. Charts keep their labels and legends, so you can still save.</div> : null}
          </div>
          <Field label="Footer text (optional)" hint={`One line, up to ${v.footer_max} characters, printed in the footer of every report page and slide.`}>
            <input maxLength={v.footer_max} value={footer} onChange={(e) => { setFooter(e.target.value.replace(/[\r\n]/g, " ")); touched(); }} />
          </Field>
          <label className="check"><input type="checkbox" checked={darkLogos} onChange={(e) => { setDarkLogos(e.target.checked); touched(); }} /> Use a separate logo on dark backgrounds</label>
          <div className="actions left">
            <button type="button" className="primary" onClick={save} disabled={bad}>Save branding</button>
            <button type="button" onClick={reset} disabled={v.preset === "pennywarden" && v.dark.preset === "pennywarden" && light.preset === "pennywarden" && dark.preset === "pennywarden"}>Reset to the PennyWarden palette</button>
            {saved ? <span className="hint" role="status">Saved.</span> : null}
          </div>
          <LogoSlot slot="full" info={v.logos.full} label="Full logo" onChanged={logosChanged}
                    hint="On report headers and title slides. PNG or JPEG, at most 2 MB. Takes effect at once." />
          <LogoSlot slot="mark" info={v.logos.mark} label="Small mark (optional)" onChanged={logosChanged}
                    hint="In report and slide footers; without it, no mark is printed. PNG or JPEG, at most 2 MB. Takes effect at once." />
          {darkLogos ? <>
            <LogoSlot slot="dark_full" info={v.logos.dark_full} label="Full logo for dark backgrounds" onChanged={logosChanged}
                      hint="Used instead of the full logo on dark slides and pages (save branding with the box ticked). Without it, the full logo is used." />
            <LogoSlot slot="dark_mark" info={v.logos.dark_mark} label="Small mark for dark backgrounds (optional)" onChanged={logosChanged}
                      hint="Used instead of the small mark on dark slides and pages. Without it, the small mark is used." />
          </> : null}
        </div>
        <Preview colors={pal.colors} series={pal.series} footer={footer} logos={{ ...v.logos, useDark: darkLogos }} org={org} dark={tab === "dark"} />
      </div>
      {dialog}
    </section>
  );
}
