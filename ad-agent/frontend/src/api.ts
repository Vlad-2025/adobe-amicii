import { useEffect } from "react";
import { QueryClient, useQuery } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 1000 } },
});

/** The channel every channel-scoped screen talks to (set by App from the URL). */
let currentChannel = "";
export const setChannel = (ch: string) => {
  currentChannel = ch;
};
export const currentCh = () => currentChannel;
/** Channel-scoped API path. */
export const C = (path: string) => `/api/ch/${currentChannel}${path}`;

export const PLATFORM_LABEL: Record<string, string> = {
  instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok", x: "X", linkedin: "LinkedIn", bluesky: "Bluesky", listening: "Social listening",
};
export const PLATFORM_COLOR: Record<string, string> = {
  instagram: "#d6249f", facebook: "#1877f2", tiktok: "#25f4ee", x: "#e7e7e7", linkedin: "#0a66c2", bluesky: "#1185fe", listening: "#9aa5b1",
};

export async function get<T = any>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function post<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const useApi = <T = any,>(key: string, path: string, enabled = true) =>
  useQuery<T>({ queryKey: [key, path], queryFn: () => get<T>(path), enabled });

/** POST that answers with a server-sent event stream; calls onEvent for each event. */
export async function postStream(path: string, onEvent: (event: string, data: any) => void, body?: unknown, method = "POST") {
  const r = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok || !r.body) throw new Error(`${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let ev = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) ev = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent(ev, JSON.parse(data));
    }
  }
}

/** Live updates: a new simulated day refreshes every query; alerts and actions go to the handlers. */
export function useLiveStream(onAlert: (a: any) => void, onAction: (a: any) => void) {
  useEffect(() => {
    const es = new EventSource("/api/stream");
    es.addEventListener("tick", () => queryClient.invalidateQueries());
    es.addEventListener("alert", (e) => onAlert(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("action", (e) => {
      onAction(JSON.parse((e as MessageEvent).data));
      queryClient.invalidateQueries();
    });
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

export const eur = (v: number | null | undefined, d = 0) =>
  v == null ? "–" : `${v < 0 ? "−" : ""}€${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
export const pct = (v: number | null | undefined, d = 1) => (v == null ? "–" : `${(v * 100).toFixed(d)}%`);

export const STATUS_VARIANT: Record<string, "positive" | "yellow" | "notice" | "negative" | "neutral"> = {
  healthy: "positive",
  watch: "yellow",
  at_risk: "notice",
  failing: "negative",
  new: "neutral",
};
export const STATUS_LABEL: Record<string, string> = {
  healthy: "Healthy",
  watch: "Watch",
  at_risk: "At risk",
  failing: "Failing",
  new: "New",
};
export const STATUS_COLOR: Record<string, string> = {
  healthy: "#5cc29b",
  watch: "#d9c45a",
  at_risk: "#e8a65a",
  failing: "#e5737a",
  new: "#8e8e8e",
};
export const HYPO_LABEL: Record<string, string> = {
  creative_fatigue: "Creative fatigue",
  segment_saturation: "Segment saturation",
  auction_pressure: "Auction pressure",
  landing_page: "Landing page / funnel",
  seasonality: "Seasonality",
  tracking: "Tracking broke",
  no_issue: "No real problem",
};
export const COMMUNITY_COLORS = ["#5aa9e6", "#f5a623", "#7fc8a9", "#c58fe6", "#ef767a", "#a3d65c", "#4fd1c5", "#f2c14e", "#9aa5b1", "#ff9f80"];
