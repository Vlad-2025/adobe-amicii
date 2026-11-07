import { useEffect, useState } from "react";
import { Button, Checkbox, Flex, Heading, Item, Picker, ProgressCircle, Text } from "@adobe/react-spectrum";
import { HYPO_LABEL, post, useApi } from "../api";
import { go } from "../App";
import { AiTag, Card } from "../components/ui";

const DIM_LABEL: Record<string, string> = { hook: "Hook", cta: "Call to action", benefit: "Benefit", emotional_angle: "Emotional angle", offer: "Offer" };

function Resonance({ scores }: { scores: Record<string, number> }) {
  return (
    <div>
      {Object.entries(scores).map(([name, s]) => (
        <div key={name} style={{ display: "grid", gridTemplateColumns: "1fr 90px 32px", gap: 6, alignItems: "center", fontSize: 12, margin: "3px 0" }}>
          <span style={{ opacity: 0.8 }}>{name}</span>
          <div style={{ background: "rgba(255,255,255,.08)", height: 8, borderRadius: 4 }}>
            <div style={{ width: `${s}%`, height: 8, borderRadius: 4, background: s >= 55 ? "#2d9d78" : s >= 40 ? "#dfbf00" : "#e68619" }} />
          </div>
          <b style={{ textAlign: "right" }}>{s.toFixed(0)}</b>
        </div>
      ))}
    </div>
  );
}

export default function CreativeStudio({ adId }: { adId?: string }) {
  const ads = useApi<any[]>("ads", "/api/ads");
  const [ad, setAd] = useState<string | undefined>(adId);
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!ad && ads.data?.length) setAd(ads.data[0].ad_id);
  }, [ads.data, ad]);
  useEffect(() => setAd(adId ?? ad), [adId]);

  const generate = async () => {
    if (!ad) return;
    setBusy(true);
    setRes(null);
    try {
      const r = await post(`/api/creatives/${ad}/variants`, {});
      setRes(r);
      setPicked(new Set(r.variants.filter((v: any) => !v.guard.length).map((v: any) => v.ad_id)));
    } finally {
      setBusy(false);
    }
  };
  const start = async () => {
    const r = await post("/api/experiments", { source_ad_id: ad, variant_ids: Array.from(picked) });
    go("experiments", String(r.id));
  };

  return (
    <Flex direction="column" gap="size-250">
      <Flex alignItems="end" gap="size-200" wrap>
        <Heading level={2} margin={0}>Creative Studio</Heading>
        <Picker label="Ad to fix" selectedKey={ad} onSelectionChange={(k) => { setAd(String(k)); setRes(null); }} width="size-3000">
          {(ads.data ?? []).map((a) => <Item key={a.ad_id}>{`${a.ad_id} — ${a.status.replace("_", " ")}`}</Item>)}
        </Picker>
        <Button variant="cta" onPress={generate} isPending={busy} isDisabled={!ad}>Generate variants</Button>
      </Flex>
      <Text UNSAFE_style={{ opacity: 0.7, fontSize: 13 }}>
        Each variant changes exactly one dimension. Code rejects variants that repeat a dimension or are &gt;0.92 similar to the original, and runs the brand guard. Resonance = how close the copy sits to what the community actually posts about (0–100, 50 = average).
      </Text>
      {busy && <ProgressCircle isIndeterminate aria-label="generating" />}
      {res && (
        <>
          <Flex gap="size-200" wrap>
            <Card title={`Target: ${res.target_community.name}`} right={<Text UNSAFE_style={{ fontSize: 12, opacity: 0.7 }}>diagnosis: {HYPO_LABEL[res.diagnosis]}</Text>}>
              <div style={{ fontSize: 14 }}>{res.target_community.persona?.one_liner}</div>
              <div style={{ fontSize: 13, marginTop: 6, opacity: 0.8 }}>Do: {res.target_community.persona?.do?.join("; ")}</div>
            </Card>
            <Card title="Marketing memory used">
              {res.memory_used.map((m: any) => (
                <div key={m.id} style={{ fontSize: 13, margin: "4px 0", display: "flex", gap: 6 }}>
                  <span style={{ color: m.winner ? "#2d9d78" : "#e34850", fontWeight: 700 }}>{m.winner ? "✓" : "✕"}</span>
                  <span>{m.insight}</span>
                </div>
              ))}
            </Card>
          </Flex>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(220px, 1fr))", gap: 16 }}>
            <Card title={`Original · ${res.original.ad_id}`}>
              <div style={{ fontWeight: 700, fontSize: 16 }}>{res.original.hook}</div>
              <div style={{ fontSize: 14, margin: "6px 0" }}>{res.original.body}</div>
              <div style={{ fontSize: 13 }}><b>CTA:</b> {res.original.cta}</div>
              <div style={{ fontSize: 13 }}><b>Offer:</b> {res.original.offer}</div>
              <div style={{ fontSize: 13, opacity: 0.7 }}>Tone: {res.original.tone} · Angle: {res.original.angle}</div>
              <div style={{ marginTop: 10 }}><Text UNSAFE_style={{ fontSize: 12, opacity: 0.7 }}>Resonance</Text><Resonance scores={res.original_resonance} /></div>
            </Card>
            {res.variants.map((v: any) => {
              const changed = (f: string) => (v[f] !== res.original[f] ? { background: "rgba(245,166,35,.18)", borderRadius: 3, padding: "0 2px" } : {});
              return (
                <Card key={v.ad_id} title={<span>{v.ad_id} <span style={{ fontSize: 11, padding: "2px 6px", borderRadius: 4, background: "#f5a623", color: "#111", marginLeft: 6 }}>{DIM_LABEL[v.changed_dimension]}</span></span>} right={<AiTag source={res.source} />}>
                  <div style={{ fontWeight: 700, fontSize: 16, ...changed("hook") }}>{v.hook}</div>
                  <div style={{ fontSize: 14, margin: "6px 0", ...changed("body") }}>{v.body}</div>
                  <div style={{ fontSize: 13, ...changed("cta") }}><b>CTA:</b> {v.cta}</div>
                  <div style={{ fontSize: 13, ...changed("offer") }}><b>Offer:</b> {v.offer}</div>
                  <div style={{ fontSize: 13, marginTop: 8 }}><b>Hypothesis:</b> {v.hypothesis}</div>
                  <div style={{ fontSize: 13, opacity: 0.8 }}><b>Expected:</b> {v.expected_effect}</div>
                  <div style={{ marginTop: 10 }}><Text UNSAFE_style={{ fontSize: 12, opacity: 0.7 }}>Resonance</Text><Resonance scores={v.resonance} /></div>
                  <div style={{ fontSize: 12, marginTop: 8 }}>
                    Similarity to original {v.similarity_to_original.toFixed(2)} ·{" "}
                    {v.guard.length ? <span style={{ color: "#e34850" }}>Brand guard: {v.guard.map((g: any) => `${g.rule} (${g.detail})`).join(", ")}</span> : <span style={{ color: "#2d9d78" }}>Brand guard passed</span>}
                  </div>
                  <Checkbox isSelected={picked.has(v.ad_id)} onChange={(on) => { const s = new Set(picked); on ? s.add(v.ad_id) : s.delete(v.ad_id); setPicked(s); }}>Include in test</Checkbox>
                </Card>
              );
            })}
          </div>
          <Flex>
            <Button variant="cta" onPress={start} isDisabled={!picked.size}>Start experiment with {picked.size} variant{picked.size === 1 ? "" : "s"} + original</Button>
          </Flex>
        </>
      )}
    </Flex>
  );
}
