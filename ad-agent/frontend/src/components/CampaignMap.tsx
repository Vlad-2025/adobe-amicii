import { useMemo, useState } from "react";
import { geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import world from "world-atlas/countries-110m.json";

/** Country polygons, parsed once for every map on the page. */
const COUNTRIES: any[] = (feature(world as any, (world as any).objects.countries) as any).features;

/** Approximate mainland centres, so overseas territories (French Guiana, Alaska, Svalbard) don't stretch the zoom. */
const CENTER: Record<string, [number, number]> = {
  Germany: [10.4, 51.1], France: [2.4, 46.6], Spain: [-3.7, 40.2], Italy: [12.5, 42.8], Netherlands: [5.3, 52.2],
  Belgium: [4.6, 50.6], Austria: [14.5, 47.6], Switzerland: [8.2, 46.8], Poland: [19.4, 52.1], Czechia: [15.5, 49.8],
  Portugal: [-8.2, 39.6], Greece: [22.6, 39.3], Romania: [24.9, 45.9], Sweden: [16.0, 62.0], Denmark: [9.5, 56.0],
  Norway: [9.0, 61.5], Finland: [26.0, 62.5], Ireland: [-8.0, 53.2], "United Kingdom": [-2.0, 53.5],
  "United States of America": [-98.0, 39.0], Canada: [-100.0, 56.0],
};

export const MAP_COLOR = { active: "#5aa9e6", expand: "#2d9d78", retreat: "#e34850", market: "#5b5b66", other: "#34343c" };
const LABEL: Record<string, string> = { active: "Active", expand: "Recommended: expand", retreat: "Recommended: retreat", market: "Market, not targeted" };

export type MapCountry = { code: string; name: string; status: "active" | "expand" | "retreat" | "market"; reason?: string; roas?: number | null; demand_change?: number | null; share?: number; news?: string; signal_note?: string };

export function CampaignMap({ countries, width = 300, height = 160 }: { countries: MapCountry[]; width?: number; height?: number }) {
  const [hover, setHover] = useState<{ name: string; c?: MapCountry; x: number; y: number } | null>(null);
  const byName = useMemo(() => Object.fromEntries(countries.map((c) => [c.name, c])), [countries]);

  const path = useMemo(() => {
    // Fit to the countries this campaign touches, padded, with a minimum span so a 2-country campaign isn't over-zoomed.
    const focus = countries.filter((c) => c.status !== "market");
    const pts = (focus.length ? focus : countries).map((c) => CENTER[c.name]).filter(Boolean);
    if (!pts.length) pts.push([10, 50]);
    let [x0, y0, x1, y1] = [Math.min(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[1]))];
    const padX = Math.max(7, (x1 - x0) * 0.3), padY = Math.max(5, (y1 - y0) * 0.3);
    [x0, x1, y0, y1] = [x0 - padX, x1 + padX, Math.max(-60, y0 - padY), Math.min(78, y1 + padY)];
    const box = { type: "Feature", properties: {}, geometry: { type: "MultiPoint", coordinates: [[x0, y0], [x1, y1], [x0, y1], [x1, y0]] } };
    return geoPath(geoMercator().fitExtent([[2, 2], [width - 2, height - 2]], box as any));
  }, [countries, width, height]);

  const shapes = useMemo(() => COUNTRIES.map((f) => ({ name: f.properties.name as string, d: path(f) || "" })).filter((s) => s.d), [path]);

  return (
    <div style={{ position: "relative", width, height, flex: "none" }} onMouseLeave={() => setHover(null)}>
      <svg width={width} height={height} style={{ display: "block", borderRadius: 6, background: "#1c1c22" }}>
        {shapes.map((s) => {
          const c = byName[s.name];
          const fill = c ? MAP_COLOR[c.status] : MAP_COLOR.other;
          const on = hover?.name === s.name;
          return (
            <path key={s.name} d={s.d} fill={fill} fillOpacity={on ? 1 : c ? 0.9 : 0.8}
              stroke={on ? "#fff" : "#1c1c22"} strokeWidth={on ? 1.2 : 0.5}
              onMouseMove={(e) => {
                const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                setHover({ name: s.name, c, x: e.clientX - r.left, y: e.clientY - r.top });
              }} />
          );
        })}
      </svg>
      {hover && (
        <div style={{
          position: "absolute", left: Math.min(hover.x + 10, width - 150), top: hover.y + 12, zIndex: 10, pointerEvents: "none",
          background: "rgba(20,20,26,0.96)", border: "1px solid #444", borderRadius: 6, padding: "6px 8px", fontSize: 12, maxWidth: 220, lineHeight: 1.35,
        }}>
          <div style={{ fontWeight: 700 }}>{hover.name}</div>
          {hover.c && <div style={{ color: MAP_COLOR[hover.c.status] === MAP_COLOR.market ? "#aaa" : MAP_COLOR[hover.c.status] }}>{LABEL[hover.c.status]}</div>}
          {hover.c?.reason && <div style={{ opacity: 0.8 }}>{hover.c.reason}</div>}
          {hover.c?.signal_note && <div style={{ opacity: 0.8 }}>Signal: {hover.c.signal_note}</div>}
          {hover.c?.news && <div style={{ opacity: 0.65, fontStyle: "italic" }}>{hover.c.news}</div>}
        </div>
      )}
    </div>
  );
}

export function MapLegend() {
  const items: [string, string][] = [["Active", MAP_COLOR.active], ["Expand", MAP_COLOR.expand], ["Retreat", MAP_COLOR.retreat], ["Other market", MAP_COLOR.market]];
  return (
    <div style={{ display: "flex", gap: 12, fontSize: 12, opacity: 0.8 }}>
      {items.map(([l, c]) => <span key={l} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><span style={{ width: 10, height: 10, borderRadius: 2, background: c }} />{l}</span>)}
    </div>
  );
}
