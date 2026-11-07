import { Flex, Heading, Text, ProgressCircle } from "@adobe/react-spectrum";
import { useApi, eur, pct, STATUS_COLOR , C } from "../api";
import { go } from "../App";
import { Card, Health, Kpi, Sparkline, Th, Info, withTerms } from "../components/ui";
import { CampaignMap, MapLegend, MAP_COLOR } from "../components/CampaignMap";

function Campaigns() {
  const q = useApi<any[]>("campaigns", C("/campaigns"));
  if (!q.data?.length) return null;
  return (
    <Card title="Campaigns by country" right={<MapLegend />}
      info={<>Hover a country for details.<br /><b>Expand</b>: demand for the category up 20%+ in a market you sell in but don't target.<br /><b>Retreat</b>: ROAS under target and behind the campaign's other countries.<br />Demand here is simulated; in production it comes from Google Trends / GDELT news volume.</>}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 16 }}>
        {q.data.map((m) => (
          <div key={m.campaign_id} style={{ width: 322, boxSizing: "border-box", border: "1px solid var(--line)", borderRadius: 10, padding: 10, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
            <div style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontWeight: 650, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name}</span>
              <span style={{ fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap" }}>
                {eur(m.spend_7d)} · {withTerms("ROAS")} <b style={{ color: m.roas_7d < m.min_roas ? "var(--red)" : "#ddd" }}>{m.roas_7d?.toFixed(2)}</b>
              </span>
            </div>
            <CampaignMap countries={m.countries} />
            <div style={{ fontSize: 12, lineHeight: 1.5, minHeight: 36, textAlign: "center" }}>
              {m.summary.expand.length > 0 && <div><span style={{ color: MAP_COLOR.expand, fontWeight: 700 }}>Expand</span> {m.summary.expand.join(", ")}</div>}
              {m.summary.retreat.length > 0 && <div><span style={{ color: MAP_COLOR.retreat, fontWeight: 700 }}>Retreat</span> {m.summary.retreat.join(", ")}</div>}
              {!m.summary.expand.length && !m.summary.retreat.length && <div style={{ color: "var(--muted)" }}>No changes suggested</div>}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function Radar() {
  const ov = useApi("overview", C("/overview"));
  const ads = useApi<any[]>("ads", C("/ads"));
  const camps = useApi<any[]>("campaigns", C("/campaigns"));
  if (!ov.data || !ads.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  const k = ov.data.kpi_7d;
  const p = ov.data.kpi_prev_7d;
  const d = (a: number, b: number) => (b ? (a - b) / b : null);
  const hc = ov.data.health_counts;
  const campName: Record<string, string> = Object.fromEntries((camps.data ?? []).map((m: any) => [m.campaign_id, m.name]));
  return (
    <Flex direction="column" gap="size-300">
      <Flex alignItems="baseline" gap="size-200" justifyContent="center" wrap>
        <Heading level={2} margin={0}>Ads Radar</Heading>
        <span style={{ fontSize: 14, color: "var(--muted)" }}>
          <b style={{ color: STATUS_COLOR.failing }}>{hc.failing} failing</b> · <b style={{ color: STATUS_COLOR.at_risk }}>{hc.at_risk} at risk</b> · {hc.watch} watch · {hc.healthy} healthy
        </span>
      </Flex>
      <Flex gap="size-200" wrap>
        <Kpi label="Spend · 7 days" value={eur(k.spend)} delta={d(k.spend, p.spend)} goodWhenUp={false} />
        <Kpi label="ROAS" value={k.roas.toFixed(2)} delta={d(k.roas, p.roas)} />
        <Kpi label="CPA" value={eur(k.cpa, 2)} delta={d(k.cpa, p.cpa)} goodWhenUp={false} info={`€ per ${ov.data.conversion_name ?? "purchase"}`} />
        <Kpi label="€ at risk" value={eur(ov.data.eur_at_risk)} accent="var(--amber)" />
      </Flex>
      <Campaigns />
      <Card title="Ads" right={<span style={{ fontSize: 12, color: "var(--muted)" }}>click a row to diagnose</span>}
        info="Sorted by health, then € at risk. Forecasts come from a LightGBM model; every number is computed by code, not the AI.">
        <table className="dtable">
          <thead>
            <tr>
              <Th left>Health</Th>
              <Th left>Ad</Th>
              <Th>CTR · 21 days</Th>
              <Th>CTR</Th>
              <Th>Frequency</Th>
              <Th>Days to fatigue</Th>
              <Th>ROAS</Th>
              <Th>€ at risk</Th>
              <Th>Alerts</Th>
            </tr>
          </thead>
          <tbody>
            {ads.data.map((a) => (
              <tr key={a.ad_id} className="click" onClick={() => go("ad", a.ad_id)}>
                <td className="l"><Health status={a.status} /></td>
                <td className="l">
                  <div style={{ fontWeight: 650 }}>{a.ad_id} <span style={{ fontWeight: 400, color: "var(--muted)", fontSize: 12 }}>{campName[a.campaign_id] ?? a.campaign_id}</span></div>
                  <div style={{ color: "#c8c8d0", fontSize: 13 }}>{a.hook}</div>
                </td>
                <td><Sparkline values={a.sparkline} color={STATUS_COLOR[a.status]} /></td>
                <td>{pct(a.ctr, 2)}</td>
                <td>{a.frequency?.toFixed(1)}</td>
                <td>
                  {a.days_to_fatigue == null ? "–" : a.days_to_fatigue <= 0 ? <span style={{ color: "var(--red)", fontWeight: 600 }}>now</span> : (
                    <span>{a.days_to_fatigue.toFixed(0)} <span style={{ color: "var(--muted)", fontSize: 12 }}>({a.dtf_low.toFixed(0)}–{a.dtf_high.toFixed(0)})</span></span>
                  )}
                </td>
                <td>{a.roas.toFixed(2)}</td>
                <td style={{ fontWeight: 650, color: a.eur_at_risk > 50 ? "var(--amber)" : undefined }}>{eur(a.eur_at_risk)}</td>
                <td style={{ fontSize: 12 }}>
                  {a.anomalies.length ? a.anomalies.map((x: any, i: number) => <div key={i}>{withTerms(x.metric.toUpperCase())} {x.z > 0 ? "▲" : "▼"} {withTerms(`${Math.abs(x.z).toFixed(1)}σ`)}</div>) : <span style={{ color: "var(--muted)" }}>–</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </Flex>
  );
}
