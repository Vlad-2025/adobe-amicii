import { Fragment, ReactNode } from "react";
import { StatusLight, Text, View, Flex } from "@adobe/react-spectrum";
import { STATUS_LABEL, STATUS_VARIANT } from "../api";

/** Plain-language definitions shown when hovering an acronym anywhere in the app. */
export const GLOSSARY: Record<string, string> = {
  CTR: "Click-through rate: clicks ÷ times the ad was shown.",
  CVR: "Conversion rate: purchases (or signups) ÷ clicks.",
  CPM: "Cost per mille: € paid for 1,000 ad views.",
  CPA: "Cost per acquisition: ad spend ÷ purchases (or signups).",
  CPC: "Cost per click: ad spend ÷ clicks.",
  ROAS: "Return on ad spend: revenue ÷ ad spend. 2.0 means €2 back for every €1 spent.",
  NMI: "Normalized mutual information: 0 = unrelated, 1 = the found communities match the seed groups exactly.",
  LLM: "Large language model: the AI that writes text (Gemini in the cloud, or a local model).",
  "σ": "Standard deviations from this ad's own normal. Beyond ±2σ is unlikely to be chance.",
  Frequency: "Average number of times one person saw the ad in the last 7 days. Above ~3, people start ignoring it.",
  "€ at risk": "Spend likely wasted over the next 7 days if nothing changes.",
  "Days to fatigue": "Forecast days until clicks fall below 70% of their peak. Brackets show the likely range.",
  Resonance: "How closely a creative matches what a community talks about (text similarity, 0–100).",
};
const TERM_RE = new RegExp(`(${Object.keys(GLOSSARY).sort((a, b) => b.length - a.length).map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");

export function Term({ k, children }: { k: string; children?: ReactNode }) {
  return (
    <span className="tip tip-term">
      {children ?? k}
      <span className="tip-box">{GLOSSARY[k]}</span>
    </span>
  );
}

/** Wrap every known acronym inside a plain string with a hover definition. */
export function withTerms(node: ReactNode): ReactNode {
  if (typeof node !== "string") return node;
  const parts = node.split(TERM_RE);
  if (parts.length === 1) return node;
  return parts.map((p, i) => (GLOSSARY[p] ? <Term key={i} k={p} /> : <Fragment key={i}>{p}</Fragment>));
}

/** Small ⓘ that explains a number or a section on hover, instead of a footnote. */
export function Info({ children }: { children: ReactNode }) {
  return (
    <span className="tip tip-icon">i<span className="tip-box">{children}</span></span>
  );
}

export function Card({ title, children, right, info, padding = "size-200" }: { title?: ReactNode; children: ReactNode; right?: ReactNode; info?: ReactNode; padding?: string }) {
  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12 }}>
      <View padding={padding as any}>
        {title && (
          <Flex justifyContent="space-between" alignItems="center" marginBottom="size-150" gap="size-200">
            <span style={{ fontWeight: 650, fontSize: 15 }}>{withTerms(title)}{info && <Info>{info}</Info>}</span>
            {right}
          </Flex>
        )}
        {children}
      </View>
    </div>
  );
}

export function Kpi({ label, value, delta, goodWhenUp = true, accent, info }: { label: string; value: string; delta?: number | null; goodWhenUp?: boolean; accent?: string; info?: ReactNode }) {
  const good = delta == null ? null : goodWhenUp ? delta >= 0 : delta <= 0;
  return (
    <div style={{ flex: 1, minWidth: 160, background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, padding: "16px 12px", textAlign: "center" }}>
      <div style={{ fontSize: 12, color: "var(--muted)" }}>{withTerms(label)}{info && <Info>{info}</Info>}</div>
      <div style={{ fontSize: 28, fontWeight: 750, margin: "4px 0 2px", color: accent, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ fontSize: 12, height: 16, color: good == null ? undefined : good ? "var(--green)" : "var(--red)" }}>
        {delta != null && <>{delta >= 0 ? "▲" : "▼"} {Math.abs(delta * 100).toFixed(0)}% <span style={{ color: "var(--muted)" }}>vs last week</span></>}
      </div>
    </div>
  );
}

export function Health({ status }: { status: string }) {
  return <StatusLight variant={STATUS_VARIANT[status] ?? "neutral"}>{STATUS_LABEL[status] ?? status}</StatusLight>;
}

export function AiTag({ source }: { source?: string }) {
  return (
    <span className="tip" style={{ flex: "none", fontSize: 10, fontWeight: 700, letterSpacing: 0.4, padding: "2px 7px", borderRadius: 4, background: "rgba(150,120,255,.16)", color: "#b9a6ff", whiteSpace: "nowrap" }}>
      AI
      <span className="tip-box" style={{ left: "auto", right: 0, transform: "none" }}>Written by AI{source ? ` (${source === "template" ? "built-in template, no AI model connected" : source})` : ""}. Numbers in this app are always computed by code.</span>
    </span>
  );
}

export function Sparkline({ values, color = "#5aa9e6", width = 110, height = 28 }: { values: number[]; color?: string; width?: number; height?: number }) {
  if (!values?.length) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const pts = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * width},${height - 2 - ((v - min) / Math.max(max - min, 1e-9)) * (height - 4)}`);
  return (
    <svg width={width} height={height}>
      <polyline fill="none" stroke={color} strokeWidth={1.6} points={pts.join(" ")} />
    </svg>
  );
}

/** Table header cell: centered, with acronym tooltips. Pass left for text columns. */
export function Th({ children, left }: { children?: ReactNode; left?: boolean }) {
  return <th className={left ? "l" : undefined}>{withTerms(children)}</th>;
}

export const th: React.CSSProperties = { textAlign: "left", fontSize: 12, fontWeight: 600, opacity: 0.7, padding: "8px 10px", borderBottom: "1px solid var(--spectrum-global-color-gray-300)", whiteSpace: "nowrap" };
export const td: React.CSSProperties = { padding: "10px", borderBottom: "1px solid var(--spectrum-global-color-gray-200)", fontSize: 14, verticalAlign: "middle" };

export const chartTheme = {
  grid: "rgba(255,255,255,0.08)",
  axis: "rgba(255,255,255,0.55)",
  tooltip: { background: "#2c2c2c", border: "1px solid #444", borderRadius: 6, color: "#eee", fontSize: 12 },
};
