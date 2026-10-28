/** 2.2.0 (#280): System/About -> Branding (Administrators). The organization's look for generated reports and
 * presentations: a palette (a ready-made one, or a custom Material 3 palette generated from a primary and a secondary
 * color and then adjusted), a full logo and a small mark, and one line of footer text. Checks, cover letters, receipts
 * and envelopes are not affected. The server validates everything again; the checks here are for the live preview. */
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

function Preview({ colors, series, footer, logos, org }: { colors: Record<string, string>; series: string[]; footer: string; logos: any; org: string }) {
  const bars = [["Golf Outing", 80], ["Raffle", 45], ["Gala", 62], ["Bake sale", 20]] as const;
  return (
    <div className="brand-preview" data-testid="branding-preview" style={{ color: colors.on_surface }} aria-label="Live preview of a report page">
      <div className="bp-head">
        <div>
          <div className="bp-title" style={{ color: colors.primary }}>Fundraising report</div>
          <div className="bp-sub" style={{ color: colors.on_surface_variant }}>{org}</div>
        </div>
        {logos.full ? <img src={`/api/system/branding/logo/full?v=${logos.full.sha256}`} alt="Full logo" /> : null}
      </div>
      <div className="bp-band" style={{ background: colors.primary, color: colors.on_primary }}>Highlights</div>
      <div className="bp-tile" style={{ background: colors.primary_container, color: colors.on_primary_container, borderColor: colors.outline_variant }}>
        Net proceeds <b>$12,450.00</b>
      </div>
      <table className="bp-table" style={{ borderColor: colors.outline }}>
        <thead><tr style={{ background: colors.surface_variant }}><th>Fundraiser</th><th>Net</th></tr></thead>
        <tbody>
          {bars.map(([n, v], i) => <tr key={n} style={{ background: i % 2 ? colors.surface : "#ffffff" }}><td>{n}</td><td>${(v * 100).toLocaleString("en-US")}.00</td></tr>)}
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
        {logos.mark ? <img src={`/api/system/branding/logo/mark?v=${logos.mark.sha256}`} alt="Small mark" /> : null}
        <span>{footer || "Fundraising report"}</span><span>Page 1 of 3</span>
      </div>
    </div>
  );
}

function LogoSlot({ slot, info, label, hint, onChanged }: { slot: "full" | "mark"; info: any; label: string; hint: string; onChanged: (v: any) => void }) {
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

export function BrandingPanel({ org }: { org: string }) {
  const [v, setV] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [preset, setPreset] = useState("pennywarden");
  const [src, setSrc] = useState({ primary: "#1f3a5f", secondary: "#d4a017" });
  const [colors, setColors] = useState<Record<Role, string>>({} as Record<Role, string>);
  const [series, setSeries] = useState<string[]>([]);
  const [footer, setFooter] = useState("");
  const [saved, setSaved] = useState(false);
  const { run, dialog } = useConfirmable();
  const take = (d: any) => {
    setV(d); setPreset(d.preset); setColors(d.colors); setSeries(d.series); setFooter(d.footer_text || "");
    setSrc({ primary: d.source_primary || d.colors.primary, secondary: d.source_secondary || d.colors.secondary });
  };
  useEffect(() => { api.get("/api/system/branding").then(take, setErr); }, []);
  const presets: Preset[] = v?.presets || [];
  const choose = (id: string) => {
    setSaved(false);
    setPreset(id);
    const p = presets.find((x) => x.id === id);
    if (p) { setColors(p.colors); setSeries(p.series); setSrc({ primary: p.source_primary, secondary: p.source_secondary }); }
  };
  const regenerate = () => {
    if (!isHex(src.primary) || !isHex(src.secondary)) return;
    const g = generate(src.primary, src.secondary);
    setColors(g.colors); setSeries(g.series); setSaved(false);
  };
  const checks = useMemo(() => (!v ? [] : (v.contrast_pairs as [Role, string][]).map(([fg, bg]) => {
    const b = bg === "white" ? "#ffffff" : colors[bg as Role];
    const r = colors[fg] && b ? contrast(colors[fg], b) : 0;
    return { fg, bg, ratio: r, ok: r >= v.minimum_contrast };
  })), [v, colors]);
  const similar = useMemo(() => {
    const out: [number, number][] = [];
    for (let i = 0; i < series.length; i++) for (let j = i + 1; j < series.length; j++) if (v && deltaE(series[i], series[j]) < v.similar_delta_e) out.push([i, j]);
    return out;
  }, [series, v]);
  if (!v) return err ? <ErrorBox error={err} /> : <Loading />;
  const roleLabel = (r: string) => (r === "white" ? "white paper" : v.roles.find((x: any) => x.id === r)?.label || r);
  const custom = preset === "custom";
  const save = async () => {
    setErr(null); setSaved(false);
    try {
      const r = await run((confirmations) => api.put("/api/system/branding", {
        preset, footer_text: footer || null, confirmations,
        ...(custom ? { source_primary: src.primary, source_secondary: src.secondary, colors, series } : {}),
      }));
      if (r) { take(r); setSaved(true); }
    } catch (x) { setErr(x); }
  };
  const reset = async () => {
    setErr(null); setSaved(false);
    try { take(await api.post("/api/system/branding/reset", {})); setSaved(true); } catch (x) { setErr(x); }
  };
  const logosChanged = (d: any) => setV((cur: any) => ({ ...cur, logos: d.logos }));
  return (
    <section className="card" aria-labelledby="brand-h">
      <h2 id="brand-h">Organization branding</h2>
      <p className="hint">Your colors and logo on generated reports and presentations: every PDF report, the fundraiser report and deck, and the
        Fiscal Year fundraising report and deck. Checks, cover letters, receipts and envelopes keep their own design.</p>
      <ErrorBox error={err} />
      <div className="brand-layout">
        <div>
          <fieldset className="lines">
            <legend>Palette</legend>
            <div className="preset-list" role="radiogroup" aria-label="Palette">
              {presets.map((p) => (
                <label key={p.id} className="check preset">
                  <input type="radio" name="brand-preset" checked={preset === p.id} onChange={() => choose(p.id)} />
                  <Swatches colors={p.colors} series={p.series} /> {p.label}{p.id === "pennywarden" ? " (default)" : ""}
                </label>
              ))}
              <label className="check preset">
                <input type="radio" name="brand-preset" checked={custom} onChange={() => { setPreset("custom"); setSaved(false); }} /> Custom
              </label>
            </div>
          </fieldset>
          {custom ? (
            <fieldset className="lines">
              <legend>Custom palette</legend>
              <div className="row form-row">
                <ColorInput id="src-primary" label="Primary color" value={src.primary} onChange={(x) => setSrc({ ...src, primary: x })} />
                <ColorInput id="src-secondary" label="Secondary color" value={src.secondary} onChange={(x) => setSrc({ ...src, secondary: x })} />
                <button type="button" onClick={regenerate} disabled={!isHex(src.primary) || !isHex(src.secondary)}>Generate recommended palette</button>
              </div>
              <p className="hint">Generates a Material 3 palette (color roles and chart colors) from your two colors. Then adjust any color below.</p>
              <details>
                <summary>Color roles</summary>
                <div className="role-grid">
                  {ROLES.map((r) => (
                      <ColorInput key={r} id={`role-${r}`} label={roleLabel(r)} value={colors[r]} onChange={(x) => { setColors({ ...colors, [r]: x }); setSaved(false); }} />
                  ))}
                </div>
              </details>
              <details>
                <summary>Chart series colors</summary>
                <div className="role-grid">
                  {series.map((c, i) => (
                      <ColorInput key={i} id={`series-${i}`} label={`Series ${i + 1}`} value={c} onChange={(x) => { const s = [...series]; s[i] = x; setSeries(s); setSaved(false); }} />
                  ))}
                </div>
              </details>
            </fieldset>
          ) : null}
          <div className="contrast-list" data-testid="branding-contrast">
            {checks.filter((c) => !c.ok).map((c) => (
              <div key={`${c.fg}-${c.bg}`} className="alert error" role="alert">
                {roleLabel(c.fg)} on {roleLabel(c.bg)}: contrast {c.ratio.toFixed(2)}:1 — text needs at least {v.minimum_contrast}:1 (WCAG AA). It can't be saved like this.
              </div>
            ))}
            {checks.length && checks.every((c) => c.ok) ? <p className="hint ok">✓ Every text color meets WCAG AA contrast.</p> : null}
            {similar.length ? <div className="alert warn" role="note">Chart series colors {similar.slice(0, 4).map(([i, j]) => `${i + 1} and ${j + 1}`).join(", ")} are hard to tell apart. Charts keep their labels and legends, so you can still save.</div> : null}
          </div>
          <Field label="Footer text (optional)" hint={`One line, up to ${v.footer_max} characters, printed in the footer of every report page.`}>
            <input maxLength={v.footer_max} value={footer} onChange={(e) => { setFooter(e.target.value.replace(/[\r\n]/g, " ")); setSaved(false); }} />
          </Field>
          <div className="actions left">
            <button type="button" className="primary" onClick={save} disabled={checks.some((c) => !c.ok)}>Save branding</button>
            <button type="button" onClick={reset} disabled={v.preset === "pennywarden" && preset === "pennywarden"}>Reset to the PennyWarden palette</button>
            {saved ? <span className="hint" role="status">Saved.</span> : null}
          </div>
          <LogoSlot slot="full" info={v.logos.full} label="Full logo" onChanged={logosChanged}
                    hint="On report headers and title slides. PNG or JPEG, at most 2 MB. Takes effect at once." />
          <LogoSlot slot="mark" info={v.logos.mark} label="Small mark (optional)" onChanged={logosChanged}
                    hint="In report and slide footers; without it, no mark is printed. PNG or JPEG, at most 2 MB. Takes effect at once." />
        </div>
        <Preview colors={colors} series={series} footer={footer} logos={v.logos} org={org} />
      </div>
      {dialog}
    </section>
  );
}
