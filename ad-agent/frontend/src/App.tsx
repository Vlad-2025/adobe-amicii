import { useEffect, useState } from "react";
import { ActionButton, Flex, Text, View, Divider, StatusLight } from "@adobe/react-spectrum";
import { useApi, useLiveStream, eur, post, queryClient } from "./api";
import Radar from "./screens/Radar";
import AdDetail from "./screens/AdDetail";
import Communities from "./screens/Communities";
import CreativeStudio from "./screens/CreativeStudio";
import Experiments from "./screens/Experiments";
import Budget from "./screens/Budget";
import Memory from "./screens/Memory";
import SimDrawer from "./components/SimDrawer";

export type Route = { page: string; arg?: string };

function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  const [page, arg] = h.split("/");
  return { page: page || "radar", arg };
}

export function go(page: string, arg?: string) {
  window.location.hash = `/${page}${arg ? "/" + arg : ""}`;
}

const NAV = [
  { page: "radar", label: "Radar", hint: "Detect" },
  { page: "communities", label: "Communities", hint: "Audiences" },
  { page: "studio", label: "Creative Studio", hint: "Fix" },
  { page: "experiments", label: "Experiments", hint: "Test" },
  { page: "budget", label: "Budget", hint: "Act" },
  { page: "memory", label: "Memory", hint: "Learn" },
];

type Toast = { id: number; text: string; tone: "negative" | "positive" | "info" };

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash());
  const [drawer, setDrawer] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const ov = useApi("overview", "/api/overview");
  const llm = useApi("llm", "/api/llm");

  useEffect(() => {
    const f = () => setRoute(parseHash());
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);

  const toast = (text: string, tone: Toast["tone"]) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  };
  useLiveStream(
    (a) => toast(`${a.ad_id} flagged ${a.status.replace("_", " ")} · ${eur(a.eur_at_risk)} at risk`, "negative"),
    (a) => {
      if (a.type === "approved") toast(`Budget proposal #${a.id} approved`, "positive");
      if (a.type === "injected") toast(`Scenario ${a.scenario} injected: ${a.name}`, "info");
      if (a.type === "creative_applied") toast(`${a.winner} replaced ${a.replaced}`, "positive");
    },
  );

  const playing = ov.data?.playing;
  const toggle = async () => {
    await post("/api/sim/control", { action: playing ? "pause" : "play" });
    queryClient.invalidateQueries();
  };

  let screen;
  switch (route.page) {
    case "ad":
      screen = <AdDetail adId={route.arg!} />;
      break;
    case "communities":
      screen = <Communities />;
      break;
    case "studio":
      screen = <CreativeStudio adId={route.arg} />;
      break;
    case "experiments":
      screen = <Experiments expId={route.arg} />;
      break;
    case "budget":
      screen = <Budget />;
      break;
    case "memory":
      screen = <Memory />;
      break;
    default:
      screen = <Radar />;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "212px 1fr", height: "100%", background: "var(--spectrum-global-color-gray-50)" }}>
      <View backgroundColor="gray-75" borderEndWidth="thin" borderColor="dark" padding="size-200">
        <Flex direction="column" height="100%" gap="size-100">
          <Flex alignItems="center" gap="size-100" marginBottom="size-200">
            <div style={{ width: 28, height: 28, borderRadius: 7, background: "#f5a623", display: "grid", placeItems: "center", fontWeight: 800, color: "#111" }}>V</div>
            <Flex direction="column">
              <Text UNSAFE_style={{ fontWeight: 700 }}>Volt</Text>
              <Text UNSAFE_style={{ fontSize: 11, opacity: 0.6 }}>Ad Fatigue Agent</Text>
            </Flex>
          </Flex>
          {NAV.map((n) => {
            const active = route.page === n.page || (n.page === "radar" && route.page === "ad");
            return (
              <a key={n.page} href={`#/${n.page}`} style={{ textDecoration: "none" }}>
                <div style={{ padding: "8px 10px", borderRadius: 6, background: active ? "var(--spectrum-global-color-gray-200)" : "transparent", color: "var(--spectrum-global-color-gray-900)", display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontWeight: active ? 700 : 400 }}>{n.label}</span>
                  <span style={{ fontSize: 11, opacity: 0.5 }}>{n.hint}</span>
                </div>
              </a>
            );
          })}
          <View flexGrow={1} />
          <Divider size="S" />
          <Text UNSAFE_style={{ fontSize: 11, opacity: 0.6, lineHeight: 1.5 }}>
            Data foundation → AI decisioning → execution. Audiences: real Bluesky communities; ad platform: simulated.
          </Text>
        </Flex>
      </View>

      <div style={{ display: "flex", flexDirection: "column", minWidth: 0, height: "100%" }}>
        <View paddingX="size-300" paddingY="size-150" borderBottomWidth="thin" borderColor="dark" backgroundColor="gray-75">
          <Flex alignItems="center" gap="size-200">
            <Text UNSAFE_style={{ fontSize: 13, opacity: 0.7 }}>Simulated day</Text>
            <Text UNSAFE_style={{ fontSize: 20, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>{ov.data?.day ?? "…"}</Text>
            <ActionButton onPress={toggle}>{playing ? "Pause" : "Play"}</ActionButton>
            <ActionButton onPress={() => post("/api/sim/control", { action: "step" })}>+1 day</ActionButton>
            <View flexGrow={1} />
            {llm.data && (
              <StatusLight variant={llm.data.provider === "cache-only" ? "neutral" : llm.data.provider === "ollama" ? "info" : "positive"}>
                LLM: {llm.data.provider === "ollama" ? `local (${llm.data.ollama_model})` : llm.data.provider === "gemini" ? (llm.data.gemini_key ? "Gemini" : "Gemini (no key → local/cache)") : "cache only"}
              </StatusLight>
            )}
            <ActionButton onPress={() => setDrawer(!drawer)}>{drawer ? "Close" : "Sim control"}</ActionButton>
          </Flex>
        </View>
        <div style={{ flex: 1, overflow: "auto", position: "relative" }}>
          <View padding="size-300" maxWidth={1400}>
            {screen}
          </View>
        </div>
      </div>

      {drawer && <SimDrawer onClose={() => setDrawer(false)} />}

      <div style={{ position: "fixed", bottom: 16, left: "50%", transform: "translateX(-50%)", display: "flex", flexDirection: "column", gap: 8, zIndex: 50 }}>
        {toasts.map((t) => (
          <div key={t.id} style={{ padding: "10px 16px", borderRadius: 8, color: "#fff", fontSize: 14, boxShadow: "0 4px 16px rgba(0,0,0,.4)", background: t.tone === "negative" ? "#c9252d" : t.tone === "positive" ? "#12805c" : "#0d66d0" }}>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}
