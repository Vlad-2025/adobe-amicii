import { ReactNode } from "react";
import { StatusLight, Text, View, Flex } from "@adobe/react-spectrum";
import { STATUS_LABEL, STATUS_VARIANT } from "../api";

export function Card({ title, children, right, padding = "size-200" }: { title?: ReactNode; children: ReactNode; right?: ReactNode; padding?: string }) {
  return (
    <View backgroundColor="gray-75" borderRadius="medium" borderWidth="thin" borderColor="dark" padding={padding as any}>
      {title && (
        <Flex justifyContent="space-between" alignItems="center" marginBottom="size-150">
          <Text UNSAFE_style={{ fontWeight: 700, fontSize: 15 }}>{title}</Text>
          {right}
        </Flex>
      )}
      {children}
    </View>
  );
}

export function Kpi({ label, value, delta, goodWhenUp = true, accent }: { label: string; value: string; delta?: number | null; goodWhenUp?: boolean; accent?: string }) {
  const good = delta == null ? null : goodWhenUp ? delta >= 0 : delta <= 0;
  return (
    <View backgroundColor="gray-75" borderRadius="medium" borderWidth="thin" borderColor="dark" padding="size-200" flex={1} minWidth={160}>
      <Text UNSAFE_style={{ fontSize: 12, opacity: 0.7 }}>{label}</Text>
      <div style={{ fontSize: 26, fontWeight: 800, marginTop: 4, color: accent, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      {delta != null && (
        <Text UNSAFE_style={{ fontSize: 12, color: good ? "#2d9d78" : "#e34850" }}>
          {delta >= 0 ? "▲" : "▼"} {Math.abs(delta * 100).toFixed(0)}% vs previous 7 days
        </Text>
      )}
    </View>
  );
}

export function Health({ status }: { status: string }) {
  return <StatusLight variant={STATUS_VARIANT[status] ?? "neutral"}>{STATUS_LABEL[status] ?? status}</StatusLight>;
}

export function AiTag({ source }: { source?: string }) {
  return (
    <span title={source ? `written by: ${source}` : "AI-written"} style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.4, padding: "2px 6px", borderRadius: 4, background: "rgba(150,120,255,.18)", color: "#b9a6ff", textTransform: "uppercase" }}>
      AI-written{source ? ` · ${source}` : ""}
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

export const th: React.CSSProperties = { textAlign: "left", fontSize: 12, fontWeight: 600, opacity: 0.7, padding: "8px 10px", borderBottom: "1px solid var(--spectrum-global-color-gray-300)", whiteSpace: "nowrap" };
export const td: React.CSSProperties = { padding: "10px", borderBottom: "1px solid var(--spectrum-global-color-gray-200)", fontSize: 14, verticalAlign: "middle" };

export const chartTheme = {
  grid: "rgba(255,255,255,0.08)",
  axis: "rgba(255,255,255,0.55)",
  tooltip: { background: "#2c2c2c", border: "1px solid #444", borderRadius: 6, color: "#eee", fontSize: 12 },
};
