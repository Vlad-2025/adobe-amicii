import { useEffect, useMemo, useRef, useState } from "react";
import { Flex, Heading, ProgressCircle, Text, Grid } from "@adobe/react-spectrum";
import ForceGraph2D from "react-force-graph-2d";
import { COMMUNITY_COLORS, pct, useApi } from "../api";
import { AiTag, Card, td, th } from "../components/ui";

export default function Communities() {
  const q = useApi("communities", "/api/communities");
  const hm = useApi<any[]>("heatmap", "/api/heatmap");
  const [sel, setSel] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(700);
  useEffect(() => {
    const f = () => setW(box.current?.clientWidth ?? 700);
    f();
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, [q.data]);
  const graph = useMemo(() => (q.data ? { nodes: q.data.graph.nodes.map((n: any) => ({ ...n })), links: q.data.graph.links.map((l: any) => ({ ...l })) } : null), [q.data]);
  if (!q.data || !graph) return <ProgressCircle isIndeterminate aria-label="loading" />;
  const comms = q.data.communities as any[];
  const meta = q.data.meta;
  const ads = Array.from(new Set((hm.data ?? []).map((r) => r.ad_id))).sort();

  return (
    <Flex direction="column" gap="size-250">
      <Flex alignItems="baseline" gap="size-200" wrap>
        <Heading level={2} margin={0}>Audience communities</Heading>
        <Text UNSAFE_style={{ opacity: 0.7 }}>
          {meta.accounts?.toLocaleString()} {meta.source === "bluesky" ? "real Bluesky accounts" : "accounts (synthetic fallback graph)"} · {comms.length} communities found by {meta.community_method} · each one a set of digital twins in the simulator
        </Text>
      </Flex>
      <Grid columns={["3fr", "2fr"]} gap="size-200">
        <Card title="Follow graph, colored by community" padding="size-100">
          <div ref={box} style={{ height: 460, overflow: "hidden", borderRadius: 6 }}>
            <ForceGraph2D
              graphData={graph}
              width={w}
              height={460}
              backgroundColor="rgba(0,0,0,0)"
              nodeRelSize={2.2}
              nodeVal={(n: any) => 0.6 + n.a}
              nodeColor={(n: any) => (sel == null || n.c === sel ? COMMUNITY_COLORS[n.c % COMMUNITY_COLORS.length] : "rgba(120,120,120,0.25)")}
              linkColor={() => "rgba(255,255,255,0.05)"}
              linkWidth={0.4}
              cooldownTicks={120}
              enableNodeDrag={false}
              onNodeClick={(n: any) => setSel(sel === n.c ? null : n.c)}
            />
          </div>
          <Text UNSAFE_style={{ fontSize: 12, opacity: 0.6 }}>Sample of {graph.nodes.length} accounts. Click a node or a card to focus a community.</Text>
        </Card>
        <Card title="Who is in each community">
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {comms.map((c) => (
              <div key={c.community_id} onClick={() => setSel(sel === c.community_id ? null : c.community_id)} style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", borderRadius: 6, background: sel === c.community_id ? "rgba(255,255,255,.08)" : undefined }}>
                <span style={{ width: 12, height: 12, borderRadius: 6, background: COMMUNITY_COLORS[c.community_id % COMMUNITY_COLORS.length] }} />
                <b style={{ flex: 1 }}>{c.name}</b>
                <span style={{ opacity: 0.6, fontSize: 13 }}>{c.size} accounts</span>
              </div>
            ))}
          </div>
          {meta.nmi_vs_seed != null && <Text UNSAFE_style={{ fontSize: 12, opacity: 0.6, display: "block", marginTop: 10 }}>Overlap with the starter packs we seeded from: NMI {meta.nmi_vs_seed.toFixed(2)}</Text>}
        </Card>
      </Grid>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
        {comms.filter((c) => sel == null || c.community_id === sel).map((c) => (
          <Card key={c.community_id} title={<span><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 5, marginRight: 8, background: COMMUNITY_COLORS[c.community_id % COMMUNITY_COLORS.length] }} />{c.name}</span>} right={c.persona && <AiTag source={c.persona.source} />}>
            {c.persona && (
              <>
                <div style={{ fontSize: 14, marginBottom: 8 }}>{c.persona.one_liner}</div>
                <div style={{ fontSize: 13, lineHeight: 1.6 }}>
                  <div><b>Interests:</b> {c.persona.interests.join(", ")}</div>
                  <div><b>Tone:</b> {c.persona.tone}</div>
                  <div><b>Best hours:</b> {c.persona.best_hours}</div>
                  <div><b>Do:</b> {c.persona.do.join("; ")}</div>
                  <div><b>Don't:</b> {c.persona.dont.join("; ")}</div>
                </div>
              </>
            )}
            <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 4 }}>
              {c.keywords.slice(0, 12).map((k: string) => (
                <span key={k} style={{ fontSize: 11, padding: "2px 6px", borderRadius: 4, background: "rgba(255,255,255,.08)" }}>{k}</span>
              ))}
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 1, height: 30, marginTop: 10 }} title="Posting activity by hour (UTC)">
              {c.hours.map((h: number, i: number) => (
                <div key={i} style={{ flex: 1, height: `${Math.max(4, (h / Math.max(...c.hours)) * 100)}%`, background: COMMUNITY_COLORS[c.community_id % COMMUNITY_COLORS.length], opacity: 0.7 }} />
              ))}
            </div>
            <div style={{ fontSize: 10, opacity: 0.5, display: "flex", justifyContent: "space-between" }}><span>00h</span><span>12h</span><span>23h UTC</span></div>
          </Card>
        ))}
      </div>

      <Card title="Ad × community heatmap: CTR change (last 3 days vs healthy baseline)">
        <table style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={th}>Ad</th>
              {comms.map((c) => <th key={c.community_id} style={{ ...th, opacity: sel == null || sel === c.community_id ? 0.8 : 0.3 }}>{c.name}</th>)}
            </tr>
          </thead>
          <tbody>
            {ads.map((ad) => (
              <tr key={ad}>
                <td style={{ ...td, fontWeight: 700 }}><a href={`#/ad/${ad}`} style={{ color: "inherit" }}>{ad}</a></td>
                {comms.map((c) => {
                  const r = hm.data!.find((x) => x.ad_id === ad && x.community_id === c.community_id);
                  if (!r) return <td key={c.community_id} style={{ ...td, opacity: 0.25, textAlign: "center" }}>·</td>;
                  const v = r.ctr_change;
                  const bg = v < -0.3 ? "rgba(227,72,80,.55)" : v < -0.15 ? "rgba(230,134,25,.45)" : v < 0.05 ? "rgba(223,191,0,.18)" : "rgba(45,157,120,.4)";
                  return (
                    <td key={c.community_id} title={`${r.status} · CTR ${pct(r.ctr_before, 2)} → ${pct(r.ctr_now, 2)} · freq ${r.frequency.toFixed(1)}`} style={{ ...td, textAlign: "center", background: bg, opacity: sel == null || sel === c.community_id ? 1 : 0.3 }}>
                      {v > 0 ? "+" : ""}{(v * 100).toFixed(0)}%
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </Flex>
  );
}
