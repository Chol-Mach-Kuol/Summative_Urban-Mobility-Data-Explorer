/**
 * map.js — Chol Mach Kuol
 * SVG choropleth map of NYC taxi zones.
 * No Leaflet — hand-drawn SVG using the GeoJSON polygons from the API.
 */

const RAMP = ["#e8f4fd", "#bdd7ee", "#6baed6", "#2171b5", "#08306b"];

function colorScale(value, min, max) {
  if (value == null || max === min) return RAMP[0];
  const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
  const i = Math.min(Math.floor(t * (RAMP.length - 1)), RAMP.length - 2);
  return RAMP[i];
}

/** Project a GeoJSON [lng, lat] coordinate to SVG [x, y] given a bounding box. */
function project([lng, lat], bbox, W, H, pad) {
  const x = pad + ((lng - bbox.minX) / (bbox.maxX - bbox.minX)) * (W - 2 * pad);
  const y = pad + ((bbox.maxY - lat) / (bbox.maxY - bbox.minY)) * (H - 2 * pad);
  return [x, y];
}

function getBBox(geojson) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const f of geojson.features) {
    const rings = f.geometry.type === "Polygon"
      ? f.geometry.coordinates
      : f.geometry.coordinates.flat();
    for (const ring of rings) {
      for (const [lng, lat] of ring) {
        if (lng < minX) minX = lng; if (lng > maxX) maxX = lng;
        if (lat < minY) minY = lat; if (lat > maxY) maxY = lat;
      }
    }
  }
  return { minX, maxX, minY, maxY };
}

function toPath(geometry, bbox, W, H, pad) {
  const rings = geometry.type === "Polygon"
    ? geometry.coordinates
    : geometry.coordinates.flat();
  return rings.map(ring =>
    ring.map((coord, i) => {
      const [x, y] = project(coord, bbox, W, H, pad);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ") + " Z"
  ).join(" ");
}

/**
 * createZoneMap(el, legendEl, geojson, { onSelect })
 * Returns { update, setSelected, zoomIn, zoomOut, reset, escName }
 */
export function createZoneMap(el, legendEl, geojson, { onSelect } = {}) {
  if (!el || !geojson?.features?.length) return null;

  const W = el.clientWidth || 560;
  const H = el.clientHeight || 480;
  const PAD = 12;

  const bbox = getBBox(geojson);
  let zoomLevel = 1;
  let selectedId = null;
  let currentStats = [];
  let currentMetric = "trips";

  // Build path elements once
  const paths = new Map();   // zone_id -> <path>
  const names = new Map();   // zone_id -> zone_name

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", "100%");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.style.cursor = "pointer";

  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  svg.appendChild(g);

  const tip = document.getElementById("tooltip");

  for (const f of geojson.features) {
    const { zone_id, zone, borough } = f.properties;
    names.set(zone_id, zone);
    const d = toPath(f.geometry, bbox, W, H, PAD);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", RAMP[0]);
    path.setAttribute("stroke", "var(--bg, #fff)");
    path.setAttribute("stroke-width", "0.4");
    path.dataset.id = zone_id;
    path.dataset.zone = zone;
    path.dataset.borough = borough;

    path.addEventListener("mouseenter", (e) => {
      if (tip) {
        const stat = currentStats.find(s => s.zone_id === zone_id);
        tip.hidden = false;
        tip.innerHTML = `<strong>${zone}</strong><div class="tip-row"><span>${borough}</span></div>` +
          (stat ? `<div class="tip-row"><span>Pickups</span><span>${stat.trips?.toLocaleString() ?? "–"}</span></div>
                   <div class="tip-row"><span>Avg speed</span><span>${stat.avg_speed_mph != null ? stat.avg_speed_mph.toFixed(1) + " mph" : "–"}</span></div>
                   <div class="tip-row"><span>Avg fare</span><span>${stat.avg_fare != null ? "$" + stat.avg_fare.toFixed(2) : "–"}</span></div>` : "");
      }
      if (zone_id !== selectedId) path.setAttribute("stroke-width", "1.5");
    });
    path.addEventListener("mousemove", (e) => {
      if (!tip) return;
      tip.style.left = `${Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8)}px`;
      tip.style.top  = `${Math.max(e.clientY - 28, 4)}px`;
    });
    path.addEventListener("mouseleave", () => {
      if (tip) tip.hidden = true;
      if (zone_id !== selectedId) path.setAttribute("stroke-width", "0.4");
    });
    path.addEventListener("click", () => {
      onSelect?.(zone_id);
    });

    g.appendChild(path);
    paths.set(zone_id, path);
  }

  el.appendChild(svg);

  function drawLegend(min, max) {
    if (!legendEl) return;
    legendEl.innerHTML = `
      <span class="legend-label">${min.toLocaleString()}</span>
      <span class="legend-swatch" style="background:linear-gradient(to right,${RAMP.join(",")})"></span>
      <span class="legend-label">${max.toLocaleString()}</span>`;
  }

  function update(stats, metric = "trips") {
    currentStats = stats;
    currentMetric = metric;
    const vals = stats.map(s => s[metric]).filter(v => v != null);
    if (!vals.length) return;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    for (const s of stats) {
      const path = paths.get(s.zone_id);
      if (!path) continue;
      const fill = colorScale(s[metric], min, max);
      path.setAttribute("fill", fill);
    }
    drawLegend(Math.round(min), Math.round(max));
  }

  function setSelected(zoneId) {
    // Reset previous
    if (selectedId != null) {
      const prev = paths.get(selectedId);
      if (prev) { prev.setAttribute("stroke", "var(--bg, #fff)"); prev.setAttribute("stroke-width", "0.4"); }
    }
    selectedId = zoneId;
    if (zoneId != null) {
      const cur = paths.get(zoneId);
      if (cur) { cur.setAttribute("stroke", "var(--accent, #e6550d)"); cur.setAttribute("stroke-width", "2"); }
    }
  }

  function zoomIn()  { zoomLevel = Math.min(zoomLevel * 1.4, 8); applyZoom(); }
  function zoomOut() { zoomLevel = Math.max(zoomLevel / 1.4, 1); applyZoom(); }
  function reset()   { zoomLevel = 1; applyZoom(); }

  function applyZoom() {
    const cx = W / 2, cy = H / 2;
    const tx = cx - zoomLevel * cx;
    const ty = cy - zoomLevel * cy;
    g.setAttribute("transform", `translate(${tx},${ty}) scale(${zoomLevel})`);
  }

  function escName(zoneId) {
    const n = names.get(zoneId) ?? String(zoneId);
    return n.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
  }

  return { update, setSelected, zoomIn, zoomOut, reset, escName };
}
