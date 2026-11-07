import { Flex, Heading, Text, ProgressCircle } from "@adobe/react-spectrum";
import { useApi, eur, pct, STATUS_COLOR , C } from "../api";
import { go } from "../App";
import { Card, Health, Kpi, Sparkline, td, th } from "../components/ui";
import { CampaignMap, MapLegend, MAP_COLOR } from "../components/CampaignMap";

function Campaigns() {
  const q = useApi<any[]>("campaigns", C("/campaigns"));
  if (!q.data?.length) return null;
  return (
    <Card title="Campaigns by country" right={<MapLegend />}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(322px, 1fr))", gap: 14 }}>
        {q.data.map((m) => (
          <div key={m.campaign_id} style={{ border: "1px solid var(--spectrum-global-color-gray-300)", borderRadius: 8, padding: 10, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name}</span>
              <span style={{ fontSize: 12, opacity: 0.7, whiteSpace: "nowrap" }}>
                {eur(m.spend_7d)} · ROAS <b style={{ color: m.roas_7d < m.min_roas ? "#e34850" : undefined }}>{m.roas_7d?.toFixed(2)}</b>
              </span>
            </div>
            <CampaignMap countries={m.countries} />
            <div style={{ fontSize: 12, lineHeight: 1.5 }}>
              {m.summary.expand.length > 0 && <div><span style={{ color: MAP_COLOR.expand, fontWeight: 700 }}>Expand:</span> {m.summary.expand.join(", ")}</div>}
              {m.summary.retreat.length > 0 && <div><span style={{ color: MAP_COLOR.retreat, fontWeight: 700 }}>Retreat:</span> {m.summary.retreat.join(", ")}</div>}
              {!m.summary.expand.length && !m.summary.retreat.length && <div style={{ opacity: 0.6 }}>No country changes recommended</div>}
            </div>
          </div>
        ))}
      </div>
      <Text UNSAFE_style={{ fontSize: 12, opacity: 0.6, display: "block", marginTop: 10 }}>
        Hover a country for details. Retreat = ROAS below the campaign target while local demand falls. Expand = category demand up 20%+ (last 3 days vs 2–4 weeks ago) in a market with no campaign yet. Demand is a Trends-style index; in production it comes from Google Trends / GDELT news volume.
      </Text>
    </Card>
  );
}

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
      <Campaigns />
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
