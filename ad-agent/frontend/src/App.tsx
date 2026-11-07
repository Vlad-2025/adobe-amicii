import { useEffect, useState } from "react";
import { ActionButton, Flex, Text, View, Divider, StatusLight } from "@adobe/react-spectrum";
import { useApi, useLiveStream, eur, post, queryClient, setChannel, PLATFORM_LABEL, PLATFORM_COLOR } from "./api";
import Radar from "./screens/Radar";
import AdDetail from "./screens/AdDetail";
import Communities from "./screens/Communities";
import CreativeStudio from "./screens/CreativeStudio";
import Experiments from "./screens/Experiments";
import Budget from "./screens/Budget";
import Memory from "./screens/Memory";
import Companies from "./screens/Companies";
import CompanyProfile from "./screens/CompanyProfile";
import NewCompany from "./screens/NewCompany";
import SimDrawer from "./components/SimDrawer";

type Route = { page: string; arg?: string; ch?: string; cid?: string };

function parseHash(): Route {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "c" && parts[1]) return { ch: parts[1], page: parts[2] || "radar", arg: parts[3] };
  if (parts[0] === "company" && parts[1]) return { page: "company", cid: parts[1] };
  if (parts[0] === "new-company") return { page: "new-company" };
  return { page: "companies" };
}

let routeCh = "";
/** Navigate inside the current channel. */
export function go(page: string, arg?: string) {
  window.location.hash = `/c/${routeCh}/${page}${arg ? "/" + arg : ""}`;
}
export function goChannel(ch: string, page = "radar") {
  window.location.hash = `/c/${ch}/${page}`;
}

const NAV = [
  { page: "radar", label: "Radar", hint: "Detect" },
  { page: "communities", label: "Audiences", hint: "Who" },
  { page: "studio", label: "Creative Studio", hint: "Fix" },
  { page: "experiments", label: "Experiments", hint: "Test" },
  { page: "budget", label: "Budget", hint: "Act" },
  { page: "memory", label: "Memory", hint: "Learn" },
];

type Toast = { id: number; text: string; tone: "negative" | "warning" | "positive" | "info" };
const TOAST_STYLE: Record<Toast["tone"], [string, string]> = {
  negative: ["#e5737a", "!"], warning: ["#e8a65a", "!"], positive: ["#5cc29b", "✓"], info: ["#6fb3e8", "i"],
};

export function PlatformDot({ platform, size = 10 }: { platform: string; size?: number }) {
  return <span style={{ display: "inline-block", width: size, height: size, borderRadius: size / 2, background: PLATFORM_COLOR[platform] ?? "#888", flexShrink: 0 }} />;
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash());
  const [drawer, setDrawer] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  routeCh = route.ch ?? "";
  setChannel(route.ch ?? "");
  const companies = useApi<any[]>("companies", "/api/companies");
  const sim = useApi("simstate", "/api/sim/state");
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
  const chName = (ch: string) => {
    for (const c of companies.data ?? []) {
      const x = c.channels.find((y: any) => y.channel_id === ch);
      if (x) return `${c.name} ${PLATFORM_LABEL[x.platform] ?? x.platform}`;
    }
    return ch;
  };
  useLiveStream(
    (a) => toast(`${chName(a.channel_id)}: ad ${a.ad_id} is now ${a.status === "failing" ? "failing" : "at risk"} · ${eur(a.eur_at_risk)} may be wasted this week`, a.status === "failing" ? "negative" : "warning"),
    (a) => {
      if (a.type === "approved") toast(`Budget proposal #${a.id} approved`, "positive");
      if (a.type === "injected") toast(`${chName(a.channel_id)}: scenario ${a.scenario} injected (${a.name})`, "info");
      if (a.type === "creative_applied") toast(`${a.winner} replaced ${a.replaced}`, "positive");
      if (a.type === "channel_added") toast(`Channel ${a.channel_id} connected`, "positive");
    },
  );

  const all = companies.data ?? [];
  const company = route.ch ? all.find((c) => c.channels.some((x: any) => x.channel_id === route.ch)) : route.cid ? all.find((c) => c.company_id === route.cid) : undefined;
  const channel = company?.channels.find((x: any) => x.channel_id === route.ch);
  const playing = sim.data?.playing;
  const control = async (action: string) => {
    await post("/api/sim/control", { action });
    queryClient.invalidateQueries();
  };

  let screen;
  if (route.ch) {
    if (channel && !channel.live) {
      screen = (
        <View padding="size-300">
          <Text>This channel has no data feed yet (status: {channel.status}). Open the company profile to see what it needs.</Text>
          <p><a href={`#/company/${company.company_id}`} style={{ color: "#5aa9e6" }}>Open {company.name}</a></p>
        </View>
      );
    } else
      switch (route.page) {
        case "ad": screen = <AdDetail key={route.ch + route.arg} adId={route.arg!} />; break;
        case "communities": screen = <Communities key={route.ch} />; break;
        case "studio": screen = <CreativeStudio key={route.ch} adId={route.arg} />; break;
        case "experiments": screen = <Experiments key={route.ch} expId={route.arg} />; break;
        case "budget": screen = <Budget key={route.ch} />; break;
        case "memory": screen = <Memory key={route.ch} />; break;
        default: screen = <Radar key={route.ch} />;
      }
  } else if (route.page === "company") screen = <CompanyProfile cid={route.cid!} />;
  else if (route.page === "new-company") screen = <NewCompany />;
  else screen = <Companies />;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "232px 1fr", height: "100%", background: "var(--bg)" }}>
      <View backgroundColor="gray-75" borderEndWidth="thin" borderColor="dark" padding="size-200" overflow="auto">
        <Flex direction="column" height="100%" gap="size-100">
          <a href="#/companies" style={{ textDecoration: "none", color: "inherit" }}>
            <Flex alignItems="center" gap="size-100" marginBottom="size-200">
              <div style={{ width: 28, height: 28, borderRadius: 7, background: "linear-gradient(135deg,#f5a623,#e34850)", display: "grid", placeItems: "center", fontWeight: 800, color: "#111" }}>A</div>
              <Flex direction="column">
                <Text UNSAFE_style={{ fontWeight: 700 }}>Ad Fatigue Agent</Text>
                <Text UNSAFE_style={{ fontSize: 11, opacity: 0.6 }}>for marketing teams</Text>
              </Flex>
            </Flex>
          </a>
          <a href="#/companies" style={{ textDecoration: "none" }}>
            <div style={{ padding: "8px 10px", borderRadius: 6, background: route.page === "companies" ? "var(--spectrum-global-color-gray-200)" : undefined, color: "var(--spectrum-global-color-gray-900)", fontWeight: route.page === "companies" ? 700 : 400 }}>All companies</div>
          </a>
          {company && (
            <>
              <Divider size="S" marginY="size-100" />
              <a href={`#/company/${company.company_id}`} style={{ textDecoration: "none", color: "inherit" }}>
                <div style={{ padding: "4px 10px", fontWeight: 700, fontSize: 15 }}>{company.name}</div>
                <div style={{ padding: "0 10px 6px", fontSize: 11, opacity: 0.6 }}>{company.industry}</div>
              </a>
              {company.channels.filter((x: any) => x.kind === "ads").map((x: any) => (
                <a key={x.channel_id} href={x.live ? `#/c/${x.channel_id}/${route.ch ? route.page : "radar"}` : `#/company/${company.company_id}`} style={{ textDecoration: "none" }}>
                  <div style={{ padding: "6px 10px", borderRadius: 6, display: "flex", alignItems: "center", gap: 8, background: x.channel_id === route.ch ? "var(--spectrum-global-color-gray-200)" : undefined, color: "var(--spectrum-global-color-gray-900)", opacity: x.live ? 1 : 0.55 }}>
                    <PlatformDot platform={x.platform} />
                    <span style={{ flex: 1, fontSize: 14 }}>{x.name}</span>
                    {x.health_counts?.failing ? <span style={{ fontSize: 11, color: "#e34850", fontWeight: 700 }}>{x.health_counts.failing}</span> : null}
                  </div>
                </a>
              ))}
            </>
          )}
          {route.ch && channel?.live && (
            <>
              <Divider size="S" marginY="size-100" />
              {NAV.map((n) => {
                const active = route.page === n.page || (n.page === "radar" && route.page === "ad");
                return (
                  <a key={n.page} href={`#/c/${route.ch}/${n.page}`} style={{ textDecoration: "none" }}>
                    <div style={{ padding: "8px 10px", borderRadius: 6, background: active ? "var(--spectrum-global-color-gray-200)" : "transparent", color: "var(--spectrum-global-color-gray-900)", display: "flex", justifyContent: "space-between" }}>
                      <span style={{ fontWeight: active ? 700 : 400 }}>{n.label}</span>
                      <span style={{ fontSize: 11, opacity: 0.5 }}>{n.hint}</span>
                    </div>
                  </a>
                );
              })}
            </>
          )}
          <View flexGrow={1} />
          <Text UNSAFE_style={{ fontSize: 11, opacity: 0.45 }}>Demo data: simulated ad feeds</Text>
        </Flex>
      </View>

      <div style={{ display: "flex", flexDirection: "column", minWidth: 0, height: "100%" }}>
        <View paddingX="size-300" paddingY="size-150" borderBottomWidth="thin" borderColor="dark" backgroundColor="gray-75">
          <Flex alignItems="center" gap="size-200" wrap>
            {channel ? (
              <Flex alignItems="center" gap="size-100">
                <PlatformDot platform={channel.platform} size={12} />
                <Text UNSAFE_style={{ fontWeight: 700 }}>{company?.name} · {PLATFORM_LABEL[channel.platform]}</Text>
                <Text UNSAFE_style={{ fontSize: 12, opacity: 0.55 }}>{channel.handle}{channel.report_lag_days ? ` · ${channel.report_lag_days}-day reporting delay` : ""}</Text>
              </Flex>
            ) : (
              <Text UNSAFE_style={{ fontWeight: 700 }}>{company ? company.name : "Your companies"}</Text>
            )}
            <View flexGrow={1} />
            <Text UNSAFE_style={{ fontSize: 13, opacity: 0.7 }}>Day</Text>
            <Text UNSAFE_style={{ fontSize: 20, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>{sim.data?.day ?? "…"}</Text>
            <ActionButton onPress={() => control(playing ? "pause" : "play")}>{playing ? "Pause" : "Play"}</ActionButton>
            <ActionButton onPress={() => control("step")}>+1 day</ActionButton>
            {llm.data && (
              <StatusLight variant={llm.data.provider === "cache-only" ? "neutral" : llm.data.provider === "ollama" ? "info" : "positive"}>
                AI: {llm.data.provider === "ollama" ? `local (${llm.data.ollama_model})` : llm.data.provider === "gemini" ? (llm.data.gemini_key ? "Gemini" : "Gemini (no key → local/cache)") : "cache only"}
              </StatusLight>
            )}
            <ActionButton onPress={() => setDrawer(!drawer)}>{drawer ? "Close" : "Sim control"}</ActionButton>
          </Flex>
        </View>
        <div style={{ flex: 1, overflow: "auto", position: "relative" }}>
          <div style={{ maxWidth: 1360, margin: "0 auto", padding: "24px 28px 48px" }}>
            {screen}
          </div>
        </div>
      </div>

      {drawer && <SimDrawer onClose={() => setDrawer(false)} channel={route.ch && channel?.live ? route.ch : undefined} />}

      <div style={{ position: "fixed", bottom: 16, left: "50%", transform: "translateX(-50%)", display: "flex", flexDirection: "column", gap: 8, zIndex: 50 }}>
        {toasts.map((t) => {
          const [c, icon] = TOAST_STYLE[t.tone];
          return (
            <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px 10px 12px", borderRadius: 10, color: "#e8e8ec", fontSize: 14, boxShadow: "0 8px 24px rgba(0,0,0,.45)", background: "#24242b", border: "1px solid #34343d", borderLeft: `4px solid ${c}` }}>
              <span style={{ width: 20, height: 20, borderRadius: 10, background: c, color: "#17171b", fontWeight: 800, fontSize: 12, display: "grid", placeItems: "center", flex: "none" }}>{icon}</span>
              {t.text}
            </div>
          );
        })}
      </div>
    </div>
  );
}
