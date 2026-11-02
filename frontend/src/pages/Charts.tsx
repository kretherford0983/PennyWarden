// v1.4.1 CR-020: dashboard charts (Recharts). Colors: reference categorical palette, validated for this app's light
// (#ffffff) and dark (#1b2128) surfaces; income = slot 1 (blue), expense = slot 2 (orange) in every chart.
import { useEffect, useRef, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, Pie, PieChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, money } from "../api";
import { ErrorBox, GROSS_BUDGET_NOTE, InfoTip } from "../components";
import { useMe } from "../App";

export const SERIES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};
export const CHROME = {
  light: { text: "#1b1f24", muted: "#5b6573", grid: "#e1e0d9", axis: "#c3c2b7", surface: "#ffffff", neutral: "#c3c2b7", other: "#898781" },
  dark: { text: "#e6eaef", muted: "#9aa6b4", grid: "#2c3440", axis: "#46515e", surface: "#1b2128", neutral: "#52606f", other: "#898781" },
};

export const CHARTS: { key: string; title: string }[] = [
  { key: "income_pie", title: "Income by budget" },
  { key: "monthly", title: "Monthly expenses and income" },
  { key: "expense_vs_budget", title: "Expense budgets: budgeted vs spent" },
  { key: "balances", title: "Bank balances (month end)" },
  { key: "expense_pie", title: "Expenses by budget" },
  { key: "cumulative_net", title: "Cumulative net (income − expenses)" },
];

const num = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v));
export const compact = (v: number) => {
  const a = Math.abs(v);
  const s = a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(a >= 1e4 ? 0 : 1)}k` : `${a.toFixed(0)}`;
  return `${v < 0 ? "-" : ""}$${s}`;
};
const pct = (s: number) => `${(s * 100).toFixed(s < 0.1 ? 1 : 0)}%`;

export default function DashboardCharts({ fys, currentFyId }: { fys: any[]; currentFyId: number | null }) {
  const { me, patchMe } = useMe();
  const theme = me.theme === "dark" ? "dark" : "light";
  const [fy, setFy] = useState<string>(currentFyId ? String(currentFyId) : fys[0] ? String(fys[0].id) : "");
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [edit, setEdit] = useState(false);
  const narrow = useNarrow(900);
  const [shown, setShown] = useState<string[]>(me.dashboard_charts ?? ["income_pie", "monthly", "expense_vs_budget"]);

  useEffect(() => {
    if (!fy) return;
    setData(null);
    api.get(`/api/dashboard/charts?fiscal_year_id=${fy}`).then(setData, setErr);
  }, [fy]);

  // Saves run one after another (never in parallel), so the last choice always wins on the server.
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(0);
  const [saveState, setSaveState] = useState<"saving" | "saved" | null>(null);
  const toggle = (key: string, on: boolean) => {
    const next = on ? CHARTS.map((c) => c.key).filter((k) => k === key || shown.includes(k)) : shown.filter((k) => k !== key);
    setShown(next); // update at once; saved for the account in the background
    patchMe({ dashboard_charts: next });
    pending.current += 1;
    setSaveState("saving");
    queue.current = queue.current
      .then(() => api.put("/api/me/preferences", { dashboard_charts: next }))
      .catch((e) => setErr(e))
      .finally(() => {
        pending.current -= 1;
        if (pending.current === 0) setSaveState("saved");
      });
  };

  if (!fys.length) return null;
  return (
    <section className="card charts" aria-labelledby="charts-h">
      <div className="charts-head">
        <h2 id="charts-h">Charts</h2>
        <label className="field-inner inline">
          <span className="field-label">Fiscal Year</span>
          <select aria-label="Charts Fiscal Year" value={fy} onChange={(e) => setFy(e.target.value)}>
            {fys.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </label>
        {saveState ? <span className="hint" role="status">{saveState === "saving" ? "Saving your chart choice…" : "Chart choice saved"}</span> : null}
        <button type="button" className="small" aria-expanded={edit} onClick={() => setEdit(!edit)}>{edit ? "Done" : "Choose charts"}</button>
      </div>
      {edit ? (
        <fieldset className="chart-picker">
          <legend>Show these charts (saved for your account)</legend>
          {CHARTS.map((c) => (
            <label key={c.key} className="check"><input type="checkbox" checked={shown.includes(c.key)} onChange={(e) => toggle(c.key, e.target.checked)} /> {c.title}</label>
          ))}
        </fieldset>
      ) : null}
      <ErrorBox error={err} />
      {!shown.length ? <p className="muted">No charts selected. Use <b>Choose charts</b> to add some.</p> : null}
      {data ? (
        <Masonry narrow={narrow} items={CHARTS.filter((c) => shown.includes(c.key)).map((c) => ({
          key: c.key, height: estimateHeight(c.key, data),
          el: <ChartCard key={c.key} title={c.title} testId={`chart-${c.key}`} info={c.key === "expense_vs_budget" ? GROSS_BUDGET_NOTE : undefined}>{renderChart(c.key, data, theme)}</ChartCard>,
        }))} />
      ) : shown.length ? <p className="hint">Loading charts…</p> : null}
    </section>
  );
}

// v1.5.0 CR-030: charts only take the height they need. Two columns; each chart goes into the column that is
// currently shorter (by estimated height), in the chosen order, so a short chart next to a tall one is followed
// directly by the next chart instead of leaving an empty gap. One column on narrow screens.
export function useNarrow(px: number) {
  const q = `(max-width: ${px}px)`;
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(q).matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return narrow;
}

function estimateHeight(key: string, d: any): number {
  const chrome = 90; // title, padding, "Show data table"
  if (key === "income_pie" || key === "expense_pie") {
    const n = (key === "income_pie" ? d.income_by_budget : d.expense_by_budget).slices.length;
    return chrome + (n ? Math.max(240, 26 * n + 40) : 100);
  }
  if (key === "expense_vs_budget") return chrome + (d.expense_vs_budget.length ? Math.max(160, 52 * d.expense_vs_budget.length + 60) : 100);
  if (key === "cumulative_net") return chrome + 240;
  return chrome + 260 + (key === "balances" ? 16 * Math.max(0, d.balances.accounts.length - 2) : 0);
}

export function Masonry({ items, narrow }: { items: { key: string; height: number; el: JSX.Element }[]; narrow: boolean }) {
  if (narrow) return <div className="chart-cols one"><div className="chart-col">{items.map((i) => i.el)}</div></div>;
  const cols: { h: number; els: JSX.Element[] }[] = [{ h: 0, els: [] }, { h: 0, els: [] }];
  for (const i of items) {
    const c = cols[0].h <= cols[1].h ? cols[0] : cols[1];
    c.els.push(i.el);
    c.h += i.height;
  }
  return <div className="chart-cols">{cols.map((c, n) => <div key={n} className="chart-col">{c.els}</div>)}</div>;
}

export function ChartCard({ title, testId, children, info }: { title: string; testId: string; children: [JSX.Element, JSX.Element] | JSX.Element[]; info?: string }) {
  const [chart, table] = children as JSX.Element[];
  return (
    <figure className="chart-card" data-testid={testId}>
      <figcaption className="chart-title">{title}{info ? <InfoTip label={`About ${title}`} text={info} /> : null}</figcaption>
      <div className="chart-body" role="img" aria-label={`${title} chart; the data is available in the table below`}>{chart}</div>
      <details className="chart-table">
        <summary>Show data table</summary>
        {table}
      </details>
    </figure>
  );
}

export function tooltipStyle(theme: "light" | "dark") {
  const c = CHROME[theme];
  return {
    contentStyle: { background: c.surface, border: `1px solid ${c.axis}`, borderRadius: 6, color: c.text, fontSize: 13 },
    labelStyle: { color: c.text, fontWeight: 600 },
    itemStyle: { color: c.text },
  };
}

export function axisProps(theme: "light" | "dark") {
  const c = CHROME[theme];
  return { tick: { fill: c.muted, fontSize: 12 }, axisLine: { stroke: c.axis }, tickLine: false as const };
}

function Empty({ what = "activity" }: { what?: string }) {
  return <p className="muted chart-empty">No {what} in this Fiscal Year yet.</p>;
}

function renderChart(key: string, d: any, theme: "light" | "dark"): JSX.Element[] {
  const s = SERIES[theme];
  const c = CHROME[theme];
  const tt = tooltipStyle(theme);
  const ax = axisProps(theme);
  const grid = <CartesianGrid stroke={c.grid} vertical={false} />;
  const moneyFmt = (v: any) => money(String(v));

  if (key === "income_pie" || key === "expense_pie") {
    const pie = key === "income_pie" ? d.income_by_budget : d.expense_by_budget;
    const rows = pie.slices.map((x: any) => ({ ...x, value: Number(x.amount) }));
    const colorOf = (x: any, i: number) => (x.other ? c.other : s[i % s.length]);
    return [
      rows.length ? (
        <div className="pie-wrap">
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie data={rows} dataKey="value" nameKey="label" innerRadius="52%" outerRadius="85%" paddingAngle={1}
                   stroke={c.surface} strokeWidth={2} isAnimationActive={false}>
                {rows.map((x: any, i: number) => <Cell key={x.label} fill={colorOf(x, i)} />)}
              </Pie>
              <Tooltip {...tt} formatter={(v: any, _n: any, p: any) => [`${moneyFmt(v)} (${pct(p.payload.share)})`, p.payload.label]} />
            </PieChart>
          </ResponsiveContainer>
          <ul className="chart-legend" aria-label="Legend">
            {rows.map((x: any, i: number) => (
              <li key={x.label}><span className="swatch" style={{ background: colorOf(x, i) }} />{x.label} <span className="muted">{pct(x.share)} · {moneyFmt(x.amount)}</span></li>
            ))}
            <li className="legend-total">Total {moneyFmt(pie.total)}</li>
          </ul>
        </div>
      ) : <Empty what={key === "income_pie" ? "income" : "expenses"} />,
      <DataTable head={["Budget", "Amount", "Share"]} rows={rows.map((x: any) => [x.label, moneyFmt(x.amount), pct(x.share)])} foot={["Total", moneyFmt(pie.total), "100%"]} />,
    ];
  }

  if (key === "monthly") {
    const rows = d.monthly.map((m: any) => ({ month: m.month, income: num(m.income), expense: num(m.expense) }));
    const any = rows.some((r: any) => r.income || r.expense);
    return [
      any ? (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
            {grid}
            <XAxis dataKey="month" {...ax} interval="preserveStartEnd" />
            <YAxis {...ax} tickFormatter={compact} width={56} />
            <Tooltip {...tt} formatter={(v: any, n: any) => [moneyFmt(v), n]} />
            <Legend wrapperStyle={{ color: c.text, fontSize: 13 }} />
            <Bar dataKey="expense" name="Expenses" fill={s[1]} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
            <Line dataKey="income" name="Income" stroke={s[0]} strokeWidth={2} dot={{ r: 4, fill: s[0], stroke: c.surface, strokeWidth: 2 }} activeDot={{ r: 5 }} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      ) : <Empty />,
      <DataTable head={["Month", "Income", "Expenses"]} rows={d.monthly.map((m: any) => [m.month, m.income === null ? "—" : moneyFmt(m.income), m.expense === null ? "—" : moneyFmt(m.expense)])} />,
    ];
  }

  if (key === "expense_vs_budget") {
    const rows = d.expense_vs_budget.map((r: any) => ({ label: r.label, budgeted: Number(r.budgeted), actual: Number(r.actual), over: r.over_budget }));
    return [
      rows.length ? (
        <ResponsiveContainer width="100%" height={Math.max(160, 52 * rows.length + 60)}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 4 }} barGap={2}>
            <CartesianGrid stroke={c.grid} horizontal={false} />
            <XAxis type="number" {...ax} tickFormatter={compact} />
            <YAxis type="category" dataKey="label" {...ax} width={140} />
            <Tooltip {...tt} formatter={(v: any, n: any) => [moneyFmt(v), n]} />
            <Legend wrapperStyle={{ color: c.text, fontSize: 13 }} />
            <Bar dataKey="budgeted" name="Budgeted" fill={c.neutral} radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={false} />
            <Bar dataKey="actual" name="Spent" fill={s[1]} radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      ) : <Empty />,
      <DataTable head={["Budget", "Budgeted", "Spent", ""]} rows={d.expense_vs_budget.map((r: any) => [r.label, moneyFmt(r.budgeted), moneyFmt(r.actual), r.over_budget ? "Over budget" : ""])} />,
    ];
  }

  if (key === "balances") {
    const accts = d.balances.accounts;
    const rows = d.months.map((m: string, i: number) => {
      const o: any = { month: m, total: num(d.balances.total[i]) };
      accts.forEach((a: any, j: number) => (o[`a${j}`] = num(a.values[i])));
      return o;
    });
    return [
      accts.length ? (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
            {grid}
            <XAxis dataKey="month" {...ax} interval="preserveStartEnd" />
            <YAxis {...ax} tickFormatter={compact} width={56} />
            <Tooltip {...tt} formatter={(v: any, n: any) => [moneyFmt(v), n]} />
            <Legend wrapperStyle={{ color: c.text, fontSize: 13 }} />
            {accts.map((a: any, j: number) => (
              <Line key={a.id} dataKey={`a${j}`} name={a.label} stroke={s[j % s.length]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />
            ))}
            {accts.length > 1 ? <Line dataKey="total" name="Total" stroke={c.text} strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={{ r: 4 }} isAnimationActive={false} /> : null}
          </LineChart>
        </ResponsiveContainer>
      ) : <p className="muted chart-empty">No register accounts.</p>,
      <DataTable head={["Month", ...accts.map((a: any) => a.label), ...(accts.length > 1 ? ["Total"] : [])]}
        rows={d.months.map((m: string, i: number) => [m, ...accts.map((a: any) => (a.values[i] === null ? "—" : moneyFmt(a.values[i]))), ...(accts.length > 1 ? [d.balances.total[i] === null ? "—" : moneyFmt(d.balances.total[i])] : [])])} />,
    ];
  }

  // cumulative_net
  const rows = d.cumulative_net.map((m: any) => ({ month: m.month, net: num(m.net) }));
  const any = d.monthly.some((m: any) => Number(m.income) || Number(m.expense));
  return [
    any ? (
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
          {grid}
          <XAxis dataKey="month" {...ax} interval="preserveStartEnd" />
          <YAxis {...ax} tickFormatter={compact} width={56} />
          <ReferenceLine y={0} stroke={c.axis} />
          <Tooltip {...tt} formatter={(v: any) => [moneyFmt(v), "Cumulative net"]} />
          <Line dataKey="net" name="Cumulative net" stroke={s[0]} strokeWidth={2} dot={{ r: 4, fill: s[0], stroke: c.surface, strokeWidth: 2 }} activeDot={{ r: 5 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    ) : <Empty />,
    <DataTable head={["Month", "Cumulative net"]} rows={d.cumulative_net.map((m: any) => [m.month, m.net === null ? "—" : moneyFmt(m.net)])} />,
  ];
}

export function DataTable({ head, rows, foot }: { head: string[]; rows: string[][]; foot?: string[] }) {
  return (
    <table className="table compact">
      <thead><tr>{head.map((h, i) => <th key={i} className={i ? "num" : ""}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((x, j) => <td key={j} className={j ? "num" : ""}>{x}</td>)}</tr>)}</tbody>
      {foot ? <tfoot><tr>{foot.map((x, j) => <th key={j} className={j ? "num" : ""}>{x}</th>)}</tr></tfoot> : null}
    </table>
  );
}
