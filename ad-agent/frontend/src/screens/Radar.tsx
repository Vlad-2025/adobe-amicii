import { Flex, Heading, Text, ProgressCircle } from "@adobe/react-spectrum";
import { useApi, eur, pct, STATUS_COLOR , C } from "../api";
import { go } from "../App";
import { Card, Health, Kpi, Sparkline, td, th } from "../components/ui";

export default function Radar() {
  const ov = useApi("overview", C("/overview"));
  const ads = useApi<any[]>("ads", C("/ads"));
  if (!ov.data || !ads.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  const k = ov.data.kpi_7d;
  const p = ov.data.kpi_prev_7d;
  const d = (a: number, b: number) => (b ? (a - b) / b : null);
  const hc = ov.data.health_counts;
  return (
    <Flex direction="column" gap="size-300">
      <Flex alignItems="baseline" gap="size-200">
        <Heading level={2} margin={0}>Ads Radar</Heading>
        <Text UNSAFE_style={{ opacity: 0.7 }}>
          {hc.failing} failing · {hc.at_risk} at risk · {hc.watch} watch · {hc.healthy} healthy — last 7 days
        </Text>
      </Flex>
      <Flex gap="size-200" wrap>
        <Kpi label="Spend (7 days)" value={eur(k.spend)} delta={d(k.spend, p.spend)} goodWhenUp={false} />
        <Kpi label="ROAS (revenue ÷ spend)" value={k.roas.toFixed(2)} delta={d(k.roas, p.roas)} />
        <Kpi label={`CPA (€ per ${ov.data.conversion_name ?? "purchase"})`} value={eur(k.cpa, 2)} delta={d(k.cpa, p.cpa)} goodWhenUp={false} />
        <Kpi label="€ at risk (next 7 days)" value={eur(ov.data.eur_at_risk)} accent="#e68619" />
      </Flex>
      <Card title="Ads, sorted by health and € at risk" right={<Text UNSAFE_style={{ fontSize: 12, opacity: 0.6 }}>Click an ad to diagnose it</Text>}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={th}>Health</th>
              <th style={th}>Ad</th>
              <th style={th}>CTR, last 21 days</th>
              <th style={th}>CTR 7d</th>
              <th style={th}>Frequency (7d)</th>
              <th style={th}>Days to fatigue</th>
              <th style={th}>ROAS 7d</th>
              <th style={th}>€ at risk</th>
              <th style={th}>Anomalies</th>
            </tr>
          </thead>
          <tbody>
            {ads.data.map((a) => (
              <tr key={a.ad_id} onClick={() => go("ad", a.ad_id)} style={{ cursor: "pointer" }}>
                <td style={td}><Health status={a.status} /></td>
                <td style={td}>
                  <div style={{ fontWeight: 700 }}>{a.ad_id} <span style={{ fontWeight: 400, opacity: 0.6, fontSize: 12 }}>{a.campaign_id.replace("camp_", "Campaign ")} · {a.ad_set_id}</span></div>
                  <div style={{ opacity: 0.75, fontSize: 13 }}>{a.hook}</div>
                </td>
                <td style={td}><Sparkline values={a.sparkline} color={STATUS_COLOR[a.status]} /></td>
                <td style={td}>{pct(a.ctr, 2)}</td>
                <td style={td}>{a.frequency?.toFixed(1)}</td>
                <td style={td}>
                  {a.days_to_fatigue == null ? "–" : a.days_to_fatigue <= 0 ? <b style={{ color: "#e34850" }}>fatigued</b> : (
                    <span>{a.days_to_fatigue.toFixed(0)} <span style={{ opacity: 0.6, fontSize: 12 }}>({a.dtf_low.toFixed(0)}–{a.dtf_high.toFixed(0)})</span></span>
                  )}
                </td>
                <td style={td}>{a.roas.toFixed(2)}</td>
                <td style={{ ...td, fontWeight: 700, color: a.eur_at_risk > 50 ? "#e68619" : undefined }}>{eur(a.eur_at_risk)}</td>
                <td style={{ ...td, fontSize: 12 }}>
                  {a.anomalies.length ? a.anomalies.map((x: any) => `${x.metric.toUpperCase()} ${x.z > 0 ? "+" : ""}${x.z}σ`).join(", ") : <span style={{ opacity: 0.4 }}>none</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Text UNSAFE_style={{ fontSize: 12, opacity: 0.6, display: "block", marginTop: 10 }}>
          Days to fatigue: LightGBM forecast of days until 3-day CTR falls below 70% of its peak (10th–90th percentile in brackets). € at risk = 7 days of spend × forecast efficiency loss. All numbers computed by code.
        </Text>
      </Card>
    </Flex>
  );
}
