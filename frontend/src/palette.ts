/** 2.2.0 (#280): the recommended Material 3 palette for organization branding, generated in the browser with Google's
 * material-color-utilities (Apache-2.0) from the primary and secondary colors the Administrator enters. The server
 * stores the resolved colors and checks them again (contrast, similar series colors); this is the generator and the
 * live preview only. The roles and the chart series tones match the ready-made palettes in services/branding.py. */
import { argbFromHex, DynamicScheme, hexFromArgb, Hct, SchemeTonalSpot, TonalPalette, Variant } from "@material/material-color-utilities";

export const ROLES = ["primary", "on_primary", "primary_container", "on_primary_container", "secondary", "on_secondary",
  "secondary_container", "on_secondary_container", "surface", "on_surface", "surface_variant", "on_surface_variant",
  "outline", "outline_variant"] as const;
export type Role = (typeof ROLES)[number];
export type Palette = { colors: Record<Role, string>; series: string[] };

export const isHex = (v: string) => /^#[0-9a-fA-F]{6}$/.test(v);

/** 2.3.0 (#386): `dark` - the Material 3 dark scheme from the same two colors, with chart tones for a dark background
 * (the dark ready-made palettes in services/branding.py were generated the same way). */
export function generate(primary: string, secondary: string, dark = false): Palette {
  const pi = argbFromHex(primary), si = argbFromHex(secondary);
  const base = new SchemeTonalSpot(Hct.fromInt(pi), dark, 0);
  const s = new DynamicScheme({
    sourceColorHct: Hct.fromInt(pi), variant: Variant.TONAL_SPOT, contrastLevel: 0, isDark: dark,
    primaryPalette: TonalPalette.fromInt(pi), secondaryPalette: TonalPalette.fromInt(si), tertiaryPalette: base.tertiaryPalette,
    neutralPalette: base.neutralPalette, neutralVariantPalette: base.neutralVariantPalette, errorPalette: base.errorPalette,
  });
  const h = hexFromArgb;
  const P = TonalPalette.fromInt(pi), S = TonalPalette.fromInt(si), T = base.tertiaryPalette, N = base.neutralPalette;
  return {
    colors: {
      primary: h(s.primary), on_primary: h(s.onPrimary), primary_container: h(s.primaryContainer), on_primary_container: h(s.onPrimaryContainer),
      secondary: h(s.secondary), on_secondary: h(s.onSecondary), secondary_container: h(s.secondaryContainer), on_secondary_container: h(s.onSecondaryContainer),
      surface: h(s.surface), on_surface: h(s.onSurface), surface_variant: h(s.surfaceVariant), on_surface_variant: h(s.onSurfaceVariant),
      outline: h(s.outline), outline_variant: h(s.outlineVariant),
    },
    series: (dark ? [P.tone(80), S.tone(70), T.tone(80), P.tone(60), S.tone(90), T.tone(60), N.tone(70), P.tone(45)]
      : [P.tone(40), S.tone(60), T.tone(40), P.tone(70), S.tone(35), T.tone(70), N.tone(50), P.tone(25)]).map(h),
  };
}

const lin = (c: number) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
const rgb = (x: string) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
const lum = (x: string) => { const [r, g, b] = rgb(x).map(lin); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };

/** The WCAG contrast ratio of two colors. */
export function contrast(a: string, b: string): number {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

function lab(x: string): [number, number, number] {
  const l = (c: number) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const [r, g, b] = rgb(x).map(l);
  const X = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, Y = 0.2126 * r + 0.7152 * g + 0.0722 * b, Z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  return [116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))];
}

export function deltaE(a: string, b: string): number {
  const p = lab(a), q = lab(b);
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
}
