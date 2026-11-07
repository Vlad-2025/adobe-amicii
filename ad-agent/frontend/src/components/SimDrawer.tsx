import { useState } from "react";
import { ActionButton, Button, Flex, Item, Picker, Slider, Switch, Text, Divider, Heading } from "@adobe/react-spectrum";
import { HYPO_LABEL, eur, pct, post, queryClient, useApi } from "../api";

export default function SimDrawer({ onClose }: { onClose: () => void }) {
  const st = useApi("simstate", "/api/sim/state");
  const ev = useApi("eval", "/api/eval");
  const [target, setTarget] = useState<string | null>(null);
  const [truth, setTruth] = useState(false);
  const tr = useApi("truth", "/api/truth", truth);
  const ctl = async (action: string, value?: number) => {
    await post("/api/sim/control", { action, value });
    queryClient.invalidateQueries();
  };
  const inject = async (scenario: string) => {
    await post("/api/sim/inject", { scenario, target_ad: target });
    queryClient.invalidateQueries();
  };
  const setLLM = async (provider: string) => {
    await post("/api/llm", { provider });
    queryClient.invalidateQueries();
  };
  const s = st.data;
  const e = ev.data;
  const lastFatigue: Record<string, number> = {};
  for (const r of tr.data?.user_state ?? []) lastFatigue[r.ad_id] = r.mean_fatigue;

  return (
    <div style={{ position: "fixed", right: 0, top: 0, bottom: 0, width: 400, background: "var(--spectrum-global-color-gray-100)", borderLeft: "1px solid var(--spectrum-global-color-gray-300)", boxShadow: "-8px 0 24px rgba(0,0,0,.4)", overflow: "auto", zIndex: 40, padding: 20 }}>
      <Flex justifyContent="space-between" alignItems="center">
        <Heading level={3} margin={0}>Sim control</Heading>
        <ActionButton isQuiet onPress={onClose}>Close</ActionButton>
      </Flex>
      {s && (
        <>
          <Flex alignItems="center" gap="size-150" marginTop="size-200" wrap>
            <Text UNSAFE_style={{ fontSize: 28, fontWeight: 800 }}>Day {s.day}</Text>
            <Button variant={s.playing ? "secondary" : "cta"} onPress={() => ctl(s.playing ? "pause" : "play")}>{s.playing ? "Pause" : "Play"}</Button>
            <ActionButton onPress={() => ctl("step")}>+1 day</ActionButton>
            <ActionButton onPress={() => ctl("reset")}>Reset</ActionButton>
          </Flex>
          <Slider label="Seconds per simulated day" minValue={0.5} maxValue={8} step={0.5} defaultValue={s.tick_seconds} onChangeEnd={(v) => ctl("speed", v)} width="100%" marginTop="size-150" />

          <Divider size="S" marginY="size-200" />
          <Heading level={4} margin={0}>Break something</Heading>
          <Text UNSAFE_style={{ fontSize: 12, opacity: 0.7 }}>Injects a scenario from today. The agent sees only platform metrics; the truth is kept for scoring.</Text>
          <Picker label="Target ad (optional)" selectedKey={target ?? "__default"} onSelectionChange={(k) => setTarget(k === "__default" ? null : String(k))} width="100%" marginTop="size-100">
            {[<Item key="__default">Scenario default</Item>, ...s.ads.map((a: string) => <Item key={a}>{a}</Item>)]}
          </Picker>
          <div style={{ display: "grid", gap: 6, marginTop: 10 }}>
            {s.scenarios.map((x: any) => (
              <button key={x.id} onClick={() => inject(x.id)} style={{ textAlign: "left", padding: "8px 10px", borderRadius: 6, border: "1px solid #555", background: "#2a2a2a", color: "#eee", cursor: "pointer" }}>
                <b>{x.id} · {x.name}</b>
                <div style={{ fontSize: 12, opacity: 0.7 }}>{x.description}</div>
              </button>
            ))}
          </div>

          <Divider size="S" marginY="size-200" />
          <Heading level={4} margin={0}>Evaluation</Heading>
          {e && (
            <>
              <Flex gap="size-300" marginY="size-100">
                <div><div style={{ fontSize: 11, opacity: 0.7 }}>Diagnosis accuracy</div><b style={{ fontSize: 22 }}>{e.accuracy == null ? "–" : pct(e.accuracy, 0)}</b> <span style={{ fontSize: 12, opacity: 0.6 }}>({e.n_scored})</span></div>
                <div><div style={{ fontSize: 11, opacity: 0.7 }}>€ protected</div><b style={{ fontSize: 22, color: "#2d9d78" }}>{eur(e.eur_protected)}</b></div>
                <div><div style={{ fontSize: 11, opacity: 0.7 }}>Community NMI</div><b style={{ fontSize: 22 }}>{e.nmi_vs_seed?.toFixed(2) ?? "–"}</b></div>
              </Flex>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <tbody>
                  {e.scenarios.map((r: any, i: number) => (
                    <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,.06)" }}>
                      <td style={{ padding: 4 }}>{r.live ? "live " : ""}{r.scenario}</td>
                      <td style={{ padding: 4 }}>{r.ad_id ?? ""}{r.day != null ? ` @${r.day}` : ""}</td>
                      <td style={{ padding: 4 }}>{truth || r.status !== "scored" ? HYPO_LABEL[r.truth] : "hidden"}</td>
                      <td style={{ padding: 4 }}>{r.status === "scored" ? `${HYPO_LABEL[r.predicted]} ${pct(r.confidence, 0)}` : r.detail}</td>
                      <td style={{ padding: 4, fontWeight: 700, color: r.correct ? "#2d9d78" : r.status === "scored" ? "#e34850" : undefined }}>{r.status === "scored" ? (r.correct ? "✓" : "✕") : "…"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <Switch isSelected={truth} onChange={setTruth} marginTop="size-150">Reveal truth</Switch>
          {truth && tr.data && (
            <div style={{ fontSize: 12, marginTop: 6 }}>
              <div style={{ opacity: 0.7 }}>Hidden layer: mean fatigue of exposed users (exposures, decaying)</div>
              {Object.entries(lastFatigue).map(([ad, f]) => (
                <div key={ad} style={{ display: "grid", gridTemplateColumns: "60px 1fr 40px", gap: 6, alignItems: "center", margin: "2px 0" }}>
                  <span>{ad}</span>
                  <div style={{ background: "rgba(255,255,255,.08)", height: 6, borderRadius: 3 }}><div style={{ width: `${Math.min(100, (f / 12) * 100)}%`, height: 6, borderRadius: 3, background: f > 6 ? "#e34850" : f > 4 ? "#e68619" : "#2d9d78" }} /></div>
                  <span>{f.toFixed(1)}</span>
                </div>
              ))}
            </div>
          )}

          <Divider size="S" marginY="size-200" />
          <Heading level={4} margin={0}>LLM</Heading>
          {e?.llm && (
            <>
              <Text UNSAFE_style={{ fontSize: 12, opacity: 0.7, display: "block" }}>
                Gemini key: {e.llm.gemini_key ? "set" : "missing"} ({e.llm.gemini_model}) · Ollama: {e.llm.ollama_reachable ? "reachable" : "not running"} ({e.llm.ollama_model}) · cache {e.llm.cache_entries} entries · calls {e.llm.calls}, cache hits {e.llm.cache_hits}
              </Text>
              <Flex gap="size-100" marginTop="size-100">
                {["gemini", "ollama", "cache-only"].map((p) => (
                  <ActionButton key={p} onPress={() => setLLM(p)} UNSAFE_style={{ outline: e.llm.provider === p ? "2px solid #f5a623" : undefined }}>{p === "ollama" ? "local (private)" : p}</ActionButton>
                ))}
              </Flex>
            </>
          )}
          <Text UNSAFE_style={{ fontSize: 11, opacity: 0.5, display: "block", marginTop: 16 }}>
            World: {s.world.source} · {s.world.accounts} accounts · embeddings: {s.world.embedder} · built {s.world.built_at}
          </Text>
        </>
      )}
    </div>
  );
}
