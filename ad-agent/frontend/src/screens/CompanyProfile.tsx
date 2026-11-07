import { useState } from "react";
import { Button, Flex, Heading, NumberField, ProgressCircle, Radio, RadioGroup, Text, TextField } from "@adobe/react-spectrum";
import { useApi, post, queryClient, PLATFORM_LABEL } from "../api";
import { goChannel, PlatformDot } from "../App";
import { Card } from "../components/ui";
import { HealthBar, STATUS_TEXT } from "./Companies";

function PlatformFacts({ p }: { p: any }) {
  const row = (k: string, v: string) => (
    <div style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 10, fontSize: 13, padding: "3px 0" }}>
      <span style={{ opacity: 0.6 }}>{k}</span><span>{v}</span>
    </div>
  );
  return (
    <div>
      {row("API", p.api)}
      {row("Reports", p.reports)}
      {row("Breakdowns", p.breakdowns)}
      {row("Audience data", p.audience)}
      {row("Access", p.access)}
      {row("Auth", p.auth)}
      {row("Cost", p.cost)}
      {row("Reporting delay", p.latency_days ? `~${p.latency_days} day` : "same day")}
    </div>
  );
}

function ConnectChannel({ cid, platforms }: { cid: string; platforms: any }) {
  const [platform, setPlatform] = useState<string>("instagram");
  const [mode, setMode] = useState("simulated");
  const [handle, setHandle] = useState("");
  const [segs, setSegs] = useState<Set<string>>(new Set());
  const [budget, setBudget] = useState(40);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const info = platforms.platforms[platform];
  const isAds = info.kind === "ads";
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await post(`/api/companies/${cid}/channels`, { platform, handle, mode, segments: Array.from(segs), daily_budget: budget });
      setResult(r);
      queryClient.invalidateQueries();
      if (r.status === "connected" && isAds && mode === "simulated") goChannel(r.channel_id);
    } catch (e: any) {
      setErr(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Connect a channel">
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        {Object.entries(platforms.platforms).filter(([k]) => k !== "listening").map(([k, v]: any) => (
          <button key={k} onClick={() => { setPlatform(k); setResult(null); }} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 8, cursor: "pointer", color: "#eee", background: platform === k ? "rgba(255,255,255,.12)" : "transparent", border: `1px solid ${platform === k ? "#f5a623" : "#555"}` }}>
            <PlatformDot platform={k} /> {v.name} <span style={{ fontSize: 11, opacity: 0.6 }}>{v.kind === "ads" ? "ads" : "audience"}</span>
          </button>
        ))}
      </div>
      <PlatformFacts p={info} />
      <Flex gap="size-300" marginTop="size-200" wrap alignItems="end">
        <TextField label={isAds ? "Account / handle" : "Handle"} value={handle} onChange={setHandle} width="size-3000" />
        {isAds && (
          <RadioGroup label="Data feed" orientation="horizontal" value={mode} onChange={setMode}>
            <Radio value="simulated">Simulated demo feed</Radio>
            <Radio value="live">Live API</Radio>
          </RadioGroup>
        )}
      </Flex>
      {isAds && mode === "simulated" && (
        <div style={{ marginTop: 14 }}>
          <Text UNSAFE_style={{ fontSize: 13, opacity: 0.8 }}>Audience segments your ad sets target (one ad set each, 2 starter ads per ad set). The platform reports results per segment, never per person.</Text>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
            {platforms.segments.map((s: any) => {
              const on = segs.has(s.key);
              return (
                <button key={s.key} title={s.examples.join(", ")} onClick={() => { const n = new Set(segs); on ? n.delete(s.key) : n.size < 6 && n.add(s.key); setSegs(n); }}
                        style={{ padding: "4px 10px", borderRadius: 14, cursor: "pointer", fontSize: 13, color: on ? "#111" : "#ddd", background: on ? "#f5a623" : "transparent", border: "1px solid #666" }}>
                  {s.label}
                </button>
              );
            })}
          </div>
          <NumberField label="Daily budget per ad set (€)" value={budget} onChange={setBudget} minValue={5} maxValue={1000} width="size-2400" marginTop="size-150" />
        </div>
      )}
      <Flex marginTop="size-200" gap="size-200" alignItems="center">
        <Button variant="cta" onPress={submit} isPending={busy} isDisabled={isAds && mode === "simulated" && segs.size === 0}>
          {isAds && mode === "simulated" ? "Connect with simulated feed" : "Connect"}
        </Button>
        {busy && <Text>Building audience twins and 30 days of history…</Text>}
      </Flex>
      {err && <Text UNSAFE_style={{ color: "#e34850", display: "block", marginTop: 8 }}>{err}</Text>}
      {result && result.status !== "connected" && (
        <div style={{ marginTop: 12, padding: 12, borderRadius: 6, background: "rgba(230,134,25,.12)", fontSize: 14 }}>
          <b>Connected, waiting for credentials.</b> Analytics will appear when the connector reports data.<br />
          <span style={{ opacity: 0.8 }}>Next steps: {result.next_steps}</span>
        </div>
      )}
      {result && result.status === "connected" && !(isAds && mode === "simulated") && (
        <div style={{ marginTop: 12, fontSize: 14 }}>{result.next_steps}</div>
      )}
    </Card>
  );
}

export default function CompanyProfile({ cid }: { cid: string }) {
  const q = useApi(`company`, `/api/companies/${cid}`);
  const pl = useApi("platforms", "/api/platforms");
  if (!q.data || !pl.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  const c = q.data;
  const b = c.config.brand;
  const eco = c.config.economics;
  const aov = eco.order_values.reduce((s: number, v: number, i: number) => s + v * eco.order_probs[i], 0);
  return (
    <Flex direction="column" gap="size-250">
      <Flex alignItems="baseline" gap="size-200" wrap>
        <a href="#/companies" style={{ color: "inherit", opacity: 0.6, fontSize: 13 }}>← Companies</a>
        <Heading level={2} margin={0}>{c.name}</Heading>
        <Text UNSAFE_style={{ opacity: 0.7 }}>{c.industry}</Text>
        {c.config.fictional && <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "rgba(255,255,255,.1)", fontWeight: 600 }}>FICTIONAL DEMO</span>}
      </Flex>
      {c.config.description && <Text>{c.config.description}</Text>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card title="Brand kit (used by the creative strategist and the brand guard)">
          <div style={{ fontSize: 14, lineHeight: 1.7 }}>
            <div><b>Product:</b> {b.product}</div>
            <div><b>Tone:</b> {b.tone}</div>
            <div><b>Target age:</b> {b.target_age}</div>
            <div><b>Banned phrases:</b> {b.banned_phrases.join(", ") || "—"}</div>
            <div><b>Competitors (never named):</b> {b.competitors.join(", ") || "—"}</div>
            <div><b>Limits:</b> headline ≤{b.limits.headline}, body ≤{b.limits.body}, CTA ≤{b.limits.cta} characters</div>
          </div>
        </Card>
        <Card title="Conversion economics">
          <div style={{ fontSize: 14, lineHeight: 1.7 }}>
            <div><b>Conversion:</b> {eco.conversion_name}</div>
            <div><b>Average value per conversion:</b> €{aov.toFixed(2)}</div>
            <div><b>Typical conversion rate (simulated feeds):</b> {(eco.base_cvr * 100).toFixed(1)}% of clicks</div>
            <div style={{ opacity: 0.7, marginTop: 6 }}>Real feeds take conversions and revenue from the pixel / conversions API of each platform.</div>
          </div>
        </Card>
      </div>
      <Card title="Connected channels">
        {c.channels.length === 0 && <Text UNSAFE_style={{ opacity: 0.6 }}>None yet.</Text>}
        {c.channels.map((x: any) => (
          <div key={x.channel_id} style={{ display: "grid", gridTemplateColumns: "16px 220px 1fr 140px 120px", gap: 12, alignItems: "center", padding: "10px 4px", borderTop: "1px solid rgba(255,255,255,.06)" }}>
            <PlatformDot platform={x.platform} />
            <div>
              <div style={{ fontWeight: 700 }}>{x.kind === "audience" ? `${PLATFORM_LABEL[x.platform]} audience` : x.name}</div>
              <div style={{ fontSize: 12, opacity: 0.6 }}>{x.handle}</div>
            </div>
            <div style={{ fontSize: 13, opacity: 0.8 }}>
              {x.kind === "audience" ? `Communities for: ${x.feeds_channels?.join(", ") || "—"}` : x.live ? `Simulated feed · data through day ${x.reported_through} · ${x.n_ads} ads` : STATUS_TEXT[x.status] ?? x.status}
              <div style={{ fontSize: 12, opacity: 0.7 }}>{x.platform_info?.api}</div>
            </div>
            {x.live ? <HealthBar counts={x.health_counts} /> : <span />}
            {x.live ? <Button variant="secondary" onPress={() => goChannel(x.channel_id)}>Open</Button> : <span style={{ fontSize: 12, opacity: 0.6 }}>{x.mode === "live" ? "live connector" : ""}</span>}
          </div>
        ))}
      </Card>
      <ConnectChannel cid={cid} platforms={pl.data} />
    </Flex>
  );
}
