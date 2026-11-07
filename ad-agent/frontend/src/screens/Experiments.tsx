import { useEffect, useState } from "react";
import { Button, Flex, Heading, ProgressCircle, Text, Grid } from "@adobe/react-spectrum";
import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { pct, post, postStream, queryClient, useApi } from "../api";
import { go } from "../App";
import { AiTag, Card, chartTheme, td, th } from "../components/ui";

const ARM_COLORS = ["#9aa5b1", "#f5a623", "#5aa9e6", "#7fc8a9", "#c58fe6"];

export default function Experiments({ expId }: { expId?: string }) {
  const list = useApi<any[]>("experiments", "/api/experiments");
  const exp = list.data?.find((e) => String(e.id) === expId) ?? list.data?.[0];
  const [days, setDays] = useState<any[]>([]);
  const [result, setResult] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);

  useEffect(() => {
    setDays(exp?.allocation_history ?? []);
    setResult(null);
    setApplied(null);
  }, [exp?.id]);

  if (!list.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  if (!exp)
    return (
      <Flex direction="column" gap="size-200">
        <Heading level={2} margin={0}>Experiments</Heading>
        <Text>No experiments yet. Generate variants in the Creative Studio and start one.</Text>
        <Button variant="cta" onPress={() => go("studio")} alignSelf="start">Open Creative Studio</Button>
      </Flex>
    );

  const arms: string[] = exp.arms.map((a: any) => a.ad_id);
  const run = async () => {
    setRunning(true);
    setDays([]);
    setResult(null);
    await postStream(`/api/experiments/${exp.id}/run`, (ev, d) => {
      if (ev === "day") setDays((x) => [...x, d]);
      if (ev === "done") setResult(d);
    });
    setRunning(false);
    queryClient.invalidateQueries({ queryKey: ["experiments"] });
  };
  const apply = async () => {
    const r = await post(`/api/experiments/${exp.id}/apply`);
    setApplied(r.applied);
    queryClient.invalidateQueries();
  };

  const alloc = days.map((d) => Object.fromEntries([["day", d.day], ...arms.map((a, i) => [a, d.allocation[i]])]));
  const pbest = days.map((d) => Object.fromEntries([["day", d.day], ...arms.map((a, i) => [a, d.p_best[i]])]));
  const last = days[days.length - 1];
  const winner = result?.winner ?? exp.winner;
  const metric = exp.plan.metric === "ctr" ? "CTR" : "Conversions / impression";

  return (
    <Flex direction="column" gap="size-250">
      <Flex alignItems="center" gap="size-200" wrap>
        <Heading level={2} margin={0}>Experiment #{exp.id}</Heading>
        <Text UNSAFE_style={{ opacity: 0.7 }}>{exp.source_ad_id} vs {arms.length - 1} variants · {metric} · status {result ? "done" : exp.status}</Text>
        <div style={{ flex: 1 }} />
        {list.data.length > 1 && (
          <select value={exp.id} onChange={(e) => go("experiments", e.target.value)} style={{ background: "#2c2c2c", color: "#eee", border: "1px solid #555", borderRadius: 4, padding: 6 }}>
            {list.data.map((e) => <option key={e.id} value={e.id}>#{e.id} {e.source_ad_id} ({e.status})</option>)}
          </select>
        )}
        <Button variant="cta" onPress={run} isPending={running} isDisabled={exp.status === "applied"}>{days.length ? "Run again" : "Run (fast-forward)"}</Button>
      </Flex>
      <Card title="Plan (computed)">
        <Text>{exp.plan.text}</Text>
      </Card>
      {winner && (
        <div style={{ padding: "14px 18px", borderRadius: 8, background: winner === exp.source_ad_id ? "#4b4b4b" : "#12805c", display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ fontSize: 18, fontWeight: 800 }}>{winner === exp.source_ad_id ? "No variant beat the original" : `Winner: ${winner}`}</div>
          {last && <div>P(best) {pct(Math.max(...last.p_best), 0)} after {last.day} simulated days</div>}
          <div style={{ flex: 1 }} />
          {winner !== exp.source_ad_id && (applied ? <b>Live: {applied} replaced {exp.source_ad_id}</b> : <Button variant="overBackground" onPress={apply} isDisabled={exp.status === "applied"}>Apply winner to live campaign</Button>)}
        </div>
      )}
      <Grid columns={["1fr", "1fr"]} gap="size-200">
        <Card title="Traffic split (Thompson sampling, re-allocated daily)">
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={alloc} stackOffset="expand">
              <CartesianGrid stroke={chartTheme.grid} />
              <XAxis dataKey="day" stroke={chartTheme.axis} fontSize={11} />
              <YAxis stroke={chartTheme.axis} fontSize={11} tickFormatter={(v) => pct(v, 0)} />
              <Tooltip contentStyle={chartTheme.tooltip} formatter={(v: any) => pct(v, 0)} labelFormatter={(d) => `day ${d}`} />
              <Legend />
              {arms.map((a, i) => <Area key={a} type="monotone" dataKey={a} stackId="1" stroke={ARM_COLORS[i]} fill={ARM_COLORS[i]} fillOpacity={0.7} isAnimationActive={false} />)}
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Probability of being best">
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={pbest}>
              <CartesianGrid stroke={chartTheme.grid} />
              <XAxis dataKey="day" stroke={chartTheme.axis} fontSize={11} />
              <YAxis stroke={chartTheme.axis} fontSize={11} domain={[0, 1]} tickFormatter={(v) => pct(v, 0)} />
              <Tooltip contentStyle={chartTheme.tooltip} formatter={(v: any) => pct(v, 1)} labelFormatter={(d) => `day ${d}`} />
              <Legend />
              {arms.map((a, i) => <Line key={a} type="monotone" dataKey={a} stroke={ARM_COLORS[i]} strokeWidth={2} dot={false} isAnimationActive={false} />)}
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </Grid>
      {last && (
        <Card title="Arms">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Arm</th><th style={th}>Changed</th><th style={th}>Hook</th><th style={th}>Impressions</th><th style={th}>Clicks</th><th style={th}>Purchases</th><th style={th}>{metric}</th><th style={th}>P(best)</th></tr></thead>
            <tbody>
              {exp.arms.map((a: any, i: number) => (
                <tr key={a.ad_id} style={{ fontWeight: a.ad_id === winner ? 700 : 400 }}>
                  <td style={td}><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 5, background: ARM_COLORS[i], marginRight: 6 }} />{a.ad_id}</td>
                  <td style={td}>{a.changed_dimension?.replace("_", " ") ?? "original"}</td>
                  <td style={td}>{a.hook}</td>
                  <td style={td}>{Math.round(last.impressions[i]).toLocaleString()}</td>
                  <td style={td}>{Math.round(last.clicks[i]).toLocaleString()}</td>
                  <td style={td}>{Math.round(last.conversions[i]).toLocaleString()}</td>
                  <td style={td}>{pct(last.rate[i], 2)}</td>
                  <td style={td}>{pct(last.p_best[i], 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {result?.learning && (
        <Card title="New learning saved to memory" right={<AiTag source={result.learning_source} />}>
          <div style={{ fontSize: 15 }}>{result.learning.insight}</div>
          <div style={{ fontSize: 13, opacity: 0.75, marginTop: 4 }}>Evidence: {result.learning.evidence}</div>
        </Card>
      )}
      <Text UNSAFE_style={{ fontSize: 12, opacity: 0.6 }}>Runs on a forked copy of the simulator (fixed random seed), so the live campaign is untouched until you apply the winner.</Text>
    </Flex>
  );
}
