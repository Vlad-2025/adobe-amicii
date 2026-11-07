import { useEffect, useState } from "react";
import { Button, Flex, Heading, ProgressCircle, Text, Grid } from "@adobe/react-spectrum";
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { HYPO_LABEL, eur, pct, post, postStream, useApi } from "../api";
import { go } from "../App";
import { AiTag, Card, Health, chartTheme, td, th } from "../components/ui";

function Metric({ data, k, label, fmt, markers, forecast, color }: any) {
  const ms = (markers || []).filter((m: any) => m.metric === k);
  const xmax = forecast ? Math.max(data[data.length - 1]?.day ?? 0, Math.min(forecast.fatigue_day_high, (data[data.length - 1]?.day ?? 0) + 14)) : undefined;
  return (
    <Card title={label} padding="size-150">
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={data} margin={{ left: 0, right: 12, top: 6, bottom: 0 }}>
          <CartesianGrid stroke={chartTheme.grid} />
          <XAxis dataKey="day" type="number" domain={["dataMin", xmax ?? "dataMax"]} stroke={chartTheme.axis} fontSize={11} label={{ value: "day", position: "insideBottomRight", fill: chartTheme.axis, fontSize: 10, offset: -2 }} />
          <YAxis stroke={chartTheme.axis} fontSize={11} tickFormatter={fmt} width={52} />
          <Tooltip contentStyle={chartTheme.tooltip} formatter={(v: any) => fmt(v)} labelFormatter={(d) => `day ${d}`} />
          {forecast && k === "ctr" && (
            <>
              <ReferenceArea x1={forecast.fatigue_day_low} x2={Math.min(forecast.fatigue_day_high, xmax!)} fill="#e34850" fillOpacity={0.12} />
              <ReferenceLine y={forecast.threshold_ctr} stroke="#e34850" strokeDasharray="4 4" label={{ value: "70% of peak", fill: "#e34850", fontSize: 10, position: "insideTopRight" }} />
            </>
          )}
          <Line type="linear" dataKey={k} stroke={color} dot={false} strokeWidth={2} isAnimationActive={false} />
          {ms.map((m: any) => {
            const row = data.find((r: any) => r.day === m.day);
            return row ? <ReferenceDot key={m.day} x={m.day} y={row[k]} r={4} fill="#e34850" stroke="none" /> : null;
          })}
        </LineChart>
      </ResponsiveContainer>
    </Card>
  );
}

export default function AdDetail({ adId }: { adId: string }) {
  const q = useApi("ad", `/api/ads/${adId}`);
  const [diag, setDiag] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [story, setStory] = useState("");
  const [storySrc, setStorySrc] = useState<string>();

  useEffect(() => {
    setDiag(null);
    setStory("");
  }, [adId]);

  const diagnose = async () => {
    setBusy(true);
    setStory("");
    const d = await post(`/api/ads/${adId}/diagnose`);
    setDiag(d);
    setBusy(false);
    await postStream(`/api/ads/${adId}/diagnose/narrative`, (ev, data) => {
      if (ev === "meta") setStorySrc(data.source);
      if (ev === "chunk") setStory((s) => s + data.text);
    }, undefined, "GET");
  };

  if (!q.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  const { ad, health, series, markers, forecast, communities } = q.data;
  const probs = diag ? Object.entries(diag.probabilities as Record<string, number>).sort((a, b) => b[1] - a[1]) : [];

  return (
    <Flex direction="column" gap="size-250">
      <Flex alignItems="center" gap="size-200" wrap>
        <a href="#/radar" style={{ color: "inherit", opacity: 0.6, fontSize: 13 }}>← Radar</a>
        <Heading level={2} margin={0}>{ad.ad_id}</Heading>
        {health && <Health status={health.status} />}
        <Text UNSAFE_style={{ opacity: 0.7 }}>“{ad.hook}” · {ad.campaign_id} · {ad.ad_set_id}</Text>
        <div style={{ flex: 1 }} />
        <Button variant="cta" onPress={diagnose} isPending={busy}>Diagnose</Button>
        <Button variant="secondary" onPress={() => go("studio", adId)}>Generate variants</Button>
      </Flex>
      {health && (
        <Flex gap="size-300" wrap>
          <Text>CTR 7d <b>{pct(health.ctr, 2)}</b></Text>
          <Text>vs peak <b>{pct(health.ctr_vs_peak, 0)}</b></Text>
          <Text>Frequency <b>{health.frequency}</b></Text>
          <Text>Days to fatigue <b>{health.days_to_fatigue <= 0 ? "already fatigued" : `${health.days_to_fatigue} (${health.dtf_low}–${health.dtf_high})`}</b></Text>
          <Text>€ at risk <b style={{ color: "#e68619" }}>{eur(health.eur_at_risk)}</b></Text>
        </Flex>
      )}

      <Grid columns={["1fr", "1fr"]} gap="size-200">
        <Metric data={series} k="ctr" label="CTR (red band = forecast fatigue window)" fmt={(v: number) => pct(v, 2)} markers={markers} forecast={forecast} color="#5aa9e6" />
        <Metric data={series} k="cvr" label="Conversion rate (purchases ÷ clicks)" fmt={(v: number) => pct(v, 1)} markers={markers} color="#7fc8a9" />
        <Metric data={series} k="cpm" label="CPM (€ per 1,000 impressions)" fmt={(v: number) => eur(v, 2)} markers={markers} color="#f5a623" />
        <Metric data={series} k="frequency" label="Frequency (impressions ÷ reach, 7 days)" fmt={(v: number) => v.toFixed(2)} color="#c58fe6" />
      </Grid>

      {diag && (
        <Grid columns={["1fr", "1fr"]} gap="size-200">
          <Card title="Root cause (probabilities computed by code)">
            {probs.map(([h, p]) => (
              <div key={h} style={{ display: "grid", gridTemplateColumns: "170px 1fr 48px", alignItems: "center", gap: 8, margin: "6px 0" }}>
                <span style={{ fontSize: 13, fontWeight: h === diag.top ? 700 : 400 }}>{HYPO_LABEL[h]}</span>
                <div style={{ background: "rgba(255,255,255,.07)", borderRadius: 4, height: 14 }}>
                  <div style={{ width: `${Math.max(p * 100, 0.5)}%`, height: 14, borderRadius: 4, background: h === diag.top ? "#f5a623" : "#6e6e6e", transition: "width .4s" }} />
                </div>
                <span style={{ fontSize: 13, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{(p * 100).toFixed(0)}%</span>
              </div>
            ))}
            <div style={{ marginTop: 14 }}>
              <Text UNSAFE_style={{ fontSize: 12, opacity: 0.7 }}>Top evidence</Text>
              <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 4 }}>
                <tbody>
                  {diag.evidence.slice(0, 6).map((e: any) => (
                    <tr key={e.key}>
                      <td style={{ ...td, fontSize: 13, padding: "6px 4px" }}>{e.label}</td>
                      <td style={{ ...td, fontSize: 13, padding: "6px 4px", fontWeight: 600 }}>{e.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="What it means" right={story ? <AiTag source={storySrc} /> : undefined}>
            <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.55, fontSize: 15, minHeight: 120 }}>{story || <span style={{ opacity: 0.5 }}>Explaining…</span>}</div>
            <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
              {(diag.top === "creative_fatigue" || diag.top === "segment_saturation") && <Button variant="cta" onPress={() => go("studio", adId)}>Generate variants</Button>}
              {diag.top !== "seasonality" && diag.top !== "no_issue" && <Button variant="secondary" onPress={() => go("budget")}>Budget actions</Button>}
            </div>
          </Card>
        </Grid>
      )}

      <Card title="By community (ad × community)">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={th}>Community</th><th style={th}>CTR before</th><th style={th}>CTR now (3d)</th><th style={th}>Change</th><th style={th}>Frequency</th><th style={th}>Status</th><th style={th}>Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {communities.map((c: any) => {
              const bad = c.ctr_change < -0.3;
              return (
                <tr key={c.community_id}>
                  <td style={td}>{c.name}</td>
                  <td style={td}>{pct(c.ctr_before, 2)}</td>
                  <td style={td}>{pct(c.ctr_now, 2)}</td>
                  <td style={{ ...td, fontWeight: 700, color: bad ? "#e34850" : c.ctr_change < -0.15 ? "#e68619" : "#2d9d78" }}>{c.ctr_change > 0 ? "+" : ""}{(c.ctr_change * 100).toFixed(0)}%</td>
                  <td style={td}>{c.frequency.toFixed(1)}</td>
                  <td style={td}>{c.status.replace("_", " ")}</td>
                  <td style={{ ...td, fontWeight: 700 }}>{c.recommendation}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </Flex>
  );
}
