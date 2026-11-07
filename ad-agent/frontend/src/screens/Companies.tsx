import { Button, Flex, Heading, ProgressCircle, Text } from "@adobe/react-spectrum";
import { useApi, eur, PLATFORM_LABEL, STATUS_COLOR } from "../api";
import { goChannel, PlatformDot } from "../App";
import { Card, Kpi } from "../components/ui";

export function HealthBar({ counts }: { counts?: Record<string, number> }) {
  if (!counts) return null;
  const order = ["failing", "at_risk", "watch", "healthy"];
  const total = order.reduce((s, k) => s + (counts[k] ?? 0), 0) || 1;
  return (
    <div title={order.map((k) => `${counts[k] ?? 0} ${k.replace("_", " ")}`).join(" · ")} style={{ display: "flex", height: 8, width: 120, borderRadius: 4, overflow: "hidden", background: "rgba(255,255,255,.08)" }}>
      {order.map((k) => <div key={k} style={{ width: `${((counts[k] ?? 0) / total) * 100}%`, background: STATUS_COLOR[k] }} />)}
    </div>
  );
}

export const STATUS_TEXT: Record<string, string> = {
  connected: "Connected", awaiting_credentials: "Needs credentials", building: "Building feed…", error: "Error",
};

export default function Companies() {
  const q = useApi<any[]>("companies", "/api/companies");
  if (!q.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  const chans = q.data.flatMap((c) => c.channels.filter((x: any) => x.live));
  const spend = chans.reduce((s: number, x: any) => s + x.kpi_7d.spend, 0);
  const risk = chans.reduce((s: number, x: any) => s + x.eur_at_risk, 0);
  const failing = chans.reduce((s: number, x: any) => s + (x.health_counts?.failing ?? 0), 0);
  return (
    <Flex direction="column" gap="size-300">
      <Flex alignItems="center" gap="size-200">
        <Heading level={2} margin={0}>Companies</Heading>
        <Text UNSAFE_style={{ opacity: 0.7 }}>Each company connects its ad accounts and audience sources. Analytics appear as soon as a connector reports data.</Text>
        <div style={{ flex: 1 }} />
        <Button variant="cta" onPress={() => (window.location.hash = "/new-company")}>New company</Button>
      </Flex>
      <Flex gap="size-200" wrap>
        <Kpi label="Ad spend, last 7 days (all channels)" value={eur(spend)} />
        <Kpi label="€ at risk, next 7 days" value={eur(risk)} accent="#e68619" />
        <Kpi label="Failing ads" value={String(failing)} accent={failing ? "#e34850" : undefined} />
        <Kpi label="Connected ad channels" value={String(chans.length)} />
      </Flex>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(440px, 1fr))", gap: 16 }}>
        {q.data.map((c) => (
          <Card key={c.company_id} title={<span>{c.name} {c.fictional && <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "rgba(255,255,255,.1)", marginLeft: 6, fontWeight: 600 }}>FICTIONAL DEMO</span>}</span>}
                right={<a href={`#/company/${c.company_id}`} style={{ color: "#5aa9e6", fontSize: 13 }}>Profile & connections →</a>}>
            <div style={{ fontSize: 13, opacity: 0.75, marginBottom: 10 }}>{c.industry}{c.description ? ` · ${c.description}` : ""}</div>
            {c.channels.length === 0 && <Text UNSAFE_style={{ opacity: 0.6 }}>No channels yet. Open the profile to connect one.</Text>}
            {c.channels.map((x: any) => (
              <div key={x.channel_id} onClick={() => (x.live ? goChannel(x.channel_id) : (window.location.hash = `/company/${c.company_id}`))}
                   style={{ display: "grid", gridTemplateColumns: "16px 1fr auto 130px 90px", gap: 10, alignItems: "center", padding: "8px 6px", borderTop: "1px solid rgba(255,255,255,.06)", cursor: "pointer" }}>
                <PlatformDot platform={x.platform} />
                <div>
                  <div style={{ fontWeight: 600 }}>{x.kind === "audience" ? `${PLATFORM_LABEL[x.platform]} audience` : x.name}</div>
                  <div style={{ fontSize: 12, opacity: 0.6 }}>{x.handle} · {x.kind === "audience" ? `feeds ${x.feeds_channels?.join(", ") || "—"}` : x.live ? `data through day ${x.reported_through}` : STATUS_TEXT[x.status] ?? x.status}</div>
                </div>
                <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10, background: x.status === "connected" ? "rgba(45,157,120,.2)" : "rgba(230,134,25,.2)", color: x.status === "connected" ? "#5fd3a5" : "#f0a54f" }}>
                  {x.kind === "audience" ? "audience" : x.live ? "simulated feed" : STATUS_TEXT[x.status] ?? x.status}
                </span>
                {x.live ? <HealthBar counts={x.health_counts} /> : <span />}
                <span style={{ fontSize: 13, textAlign: "right", color: x.eur_at_risk > 300 ? "#e68619" : undefined }}>{x.live ? `${eur(x.eur_at_risk)} at risk` : ""}</span>
              </div>
            ))}
          </Card>
        ))}
      </div>
    </Flex>
  );
}
