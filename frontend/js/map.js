/**
 * map.js - the taxi zone map, drawn as SVG from the zone GeoJSON.
 *
 * Projection: at city scale the Earth is flat enough to use a simple
 * "equirectangular" projection. One degree of longitude is shorter than one
 * degree of latitude at New York's latitude (~40.7 N), so x is scaled by
 * cos(40.7 deg) to avoid a stretched-looking city.
 *
 * Zoom and pan work by changing the SVG viewBox (the visible window).
 */

import { BLUE_RAMP, hideTooltip, rampLegend, showTooltip } from "./charts.js";
import { esc, fmt } from "./api.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const LAT0 = 40.7;
const KX = Math.cos((LAT0 * Math.PI) / 180);
const SCALE = 1000;                     // degrees -> SVG units
const MIN_RIDES_FOR_AVERAGES = 30;      // fewer rides = averages too noisy to colour

const project = ([lon, lat]) => [(lon + 74.3) * KX * SCALE, (41.0 - lat) * SCALE];

function ringToPath(ring) {
  return ring.map((pt, i) => {
    const [x, y] = project(pt);
    return `${i ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
  }).join("") + "Z";
}

function geometryToPath(geom) {
  const polygons = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  return polygons.map((rings) => rings.map(ringToPath).join("")).join("");
}

export const METRICS = {
  trips: { label: "Pickups", format: fmt.compact, needsVolume: false },
  avg_speed_mph: { label: "Average speed (mph)", format: (v) => v.toFixed(1), needsVolume: true },
  fare_per_mile: { label: "Fare per mile", format: fmt.money, needsVolume: true },
  avg_fare: { label: "Average fare", format: fmt.money0, needsVolume: true },
  avg_tip_pct: { label: "Card tip %", format: (v) => `${v.toFixed(0)}%`, needsVolume: true },
};

export function createZoneMap(container, legendEl, geojson, { onSelect }) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("aria-hidden", "true");
  const layer = document.createElementNS(SVG_NS, "g");
  svg.appendChild(layer);
  container.appendChild(svg);

  const paths = new Map();          // zone_id -> <path>
  const names = new Map();          // zone_id -> {zone, borough}
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  for (const f of geojson.features) {
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", geometryToPath(f.geometry));
    p.setAttribute("class", "zone");
    p.setAttribute("fill-rule", "evenodd");
    p.dataset.zone = f.properties.zone_id;
    layer.appendChild(p);
    paths.set(f.properties.zone_id, p);
    names.set(f.properties.zone_id, f.properties);

    const polygons = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const rings of polygons) for (const pt of rings[0]) {
      const [x, y] = project(pt);
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }

  /* ---------------- zoom & pan via the viewBox ---------------- */
  const pad = 10;
  const home = { x: minX - pad, y: minY - pad, w: maxX - minX + 2 * pad, h: maxY - minY + 2 * pad };
  let view = { ...home };
  const apply = () => svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  apply();

  function zoomAt(factor, cx = view.x + view.w / 2, cy = view.y + view.h / 2) {
    const w = Math.min(home.w * 1.5, Math.max(home.w / 25, view.w * factor));
    const h = (w / view.w) * view.h;
    view = { x: cx - ((cx - view.x) / view.w) * w, y: cy - ((cy - view.y) / view.h) * h, w, h };
    apply();
  }

  function toSvgPoint(clientX, clientY) {
    const box = svg.getBoundingClientRect();
    // preserveAspectRatio "xMidYMid meet": work out the rendered scale
    const scale = Math.min(box.width / view.w, box.height / view.h);
    const offX = (box.width - view.w * scale) / 2;
    const offY = (box.height - view.h * scale) / 2;
    return { x: view.x + (clientX - box.left - offX) / scale, y: view.y + (clientY - box.top - offY) / scale, scale };
  }

  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const pt = toSvgPoint(e.clientX, e.clientY);
    zoomAt(e.deltaY > 0 ? 1.2 : 1 / 1.2, pt.x, pt.y);
  }, { passive: false });

  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY, view: { ...view }, moved: false };
  });
  window.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    if (!drag.moved) {
      drag.moved = true;
      container.classList.add("dragging");
      hideTooltip();
    }
    const { scale } = toSvgPoint(e.clientX, e.clientY);
    view = { ...drag.view, x: drag.view.x - dx / scale, y: drag.view.y - dy / scale };
    apply();
  });
  window.addEventListener("pointerup", () => {
    if (drag?.moved) {
      // Swallow the click that follows a drag so panning never selects a zone.
      svg.addEventListener("click", (ev) => ev.stopPropagation(), { capture: true, once: true });
    }
    drag = null;
    container.classList.remove("dragging");
  });

  /* ---------------- hover & click ---------------- */
  let values = new Map();
  let metric = "trips";

  layer.addEventListener("pointermove", (e) => {
    if (drag?.moved) return;
    const id = Number(e.target.dataset.zone);
    if (!id) return;
    const info = names.get(id);
    const row = values.get(id);
    const m = METRICS[metric];
    const rows = [["Pickups", fmt.int(row?.trips ?? 0)]];
    if (metric !== "trips") {
      const v = row?.[metric];
      rows.push([m.label, v != null && row.trips >= MIN_RIDES_FOR_AVERAGES ? m.format(v) : "too few rides"]);
    }
    showTooltip(e.clientX, e.clientY, `${info.zone} · ${info.borough}`, rows);
  });
  layer.addEventListener("pointerleave", hideTooltip);
  layer.addEventListener("click", (e) => {
    const id = Number(e.target.dataset.zone);
    if (id) onSelect(id);
  });

  /* ---------------- public API ---------------- */
  return {
    zoomIn: () => zoomAt(1 / 1.5),
    zoomOut: () => zoomAt(1.5),
    reset: () => { view = { ...home }; apply(); },

    /**
     * Colour every zone. Uses QUANTILE classes: each colour step holds about
     * the same number of zones. Pickups are extremely skewed (Midtown has
     * thousands of times more than most of Queens), so equal-width steps
     * would paint almost every zone the lightest colour.
     */
    update(rows, newMetric) {
      metric = newMetric;
      values = new Map(rows.map((r) => [r.zone_id, r]));
      const m = METRICS[metric];
      const usable = rows.filter((r) => r[metric] != null && (!m.needsVolume || r.trips >= MIN_RIDES_FOR_AVERAGES));
      const sorted = usable.map((r) => r[metric]).sort((a, b) => a - b);
      const k = BLUE_RAMP.length;
      const breaks = [];
      for (let i = 1; i < k; i++) breaks.push(sorted[Math.floor((i / k) * (sorted.length - 1))]);
      const classOf = (v) => {
        let c = 0;
        while (c < breaks.length && v > breaks[c]) c++;
        return c;
      };
      const usableIds = new Set(usable.map((r) => r.zone_id));

      for (const [id, path] of paths) {
        const r = values.get(id);
        path.setAttribute("fill", usableIds.has(id) ? BLUE_RAMP[classOf(r[metric])] : "var(--no-data)");
      }
      rampLegend(legendEl, {
        title: m.label,
        ramp: BLUE_RAMP,
        minLabel: sorted.length ? m.format(sorted[0]) : "–",
        maxLabel: sorted.length ? m.format(sorted[sorted.length - 1]) : "–",
        noData: m.needsVolume ? `Fewer than ${MIN_RIDES_FOR_AVERAGES} rides` : "No pickups",
      });
    },

    setSelected(zoneId) {
      for (const [id, path] of paths) {
        const on = id === zoneId;
        path.classList.toggle("selected", on);
        if (on) layer.appendChild(path);   // bring to front so the outline is not hidden
      }
    },

    zoneName: (id) => names.get(id)?.zone,
    escName: (id) => esc(names.get(id)?.zone ?? `Zone ${id}`),
  };
}