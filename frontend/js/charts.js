/**
 * charts.js - small hand-written SVG chart toolkit.
 *
 * No chart library: each chart is a few SVG shapes we position ourselves.
 * That keeps the dashboard dependency-free (works offline) and shows how a
 * chart actually works: scale data -> pixels, draw marks, add a hover layer.
 */

import { esc } from "./api.js";

const SVG_NS = "http://www.w3.org/2000/svg";

/* ------------------------------------------------------------------------ */
/* Colour ramps (light -> dark = low -> high)                                */
/* ------------------------------------------------------------------------ */
export const BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
// Orange ramp, used for congestion (darker = slower traffic)
export const ORANGE_RAMP = ["#fde4d8", "#f8c1a7", "#f39b74", "#eb6834", "#c9521f", "#9f3f15", "#73300f"];

/** Linear position (0..1) -> colour from a ramp. */
export function rampColor(ramp, t) {
  const clamped = Math.max(0, Math.min(1, t));
  return ramp[Math.min(ramp.length - 1, Math.floor(clamped * ramp.length))];
}

/* ------------------------------------------------------------------------ */
/* Shared tooltip                                                            */
/* ------------------------------------------------------------------------ */
const tip = () => document.getElementById("tooltip");

/** rows: [[label, value], ...] */
export function showTooltip(x, y, title, rows) {
  const el = tip();
  el.innerHTML = `<strong>${esc(title)}</strong>` +
    rows.map(([k, v]) => `<div class="tt-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("");
  el.hidden = false;
  const pad = 14;
  const { width, height } = el.getBoundingClientRect();
  let left = x + pad;
  let top = y + pad;
  if (left + width > window.innerWidth - 8) left = x - width - pad;
  if (top + height > window.innerHeight - 8) top = y - height - pad;
  el.style.left = `${Math.max(8, left)}px`;
  el.style.top = `${Math.max(8, top)}px`;
}

export function hideTooltip() {
  tip().hidden = true;
}

/* ------------------------------------------------------------------------ */
/* Helpers                                                                   */
/* ------------------------------------------------------------------------ */
function el(tag, attrs = {}, parent) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

/** Round axis numbers to friendly steps (1, 2, 5 x 10^n). */
function niceTicks(min, max, count = 4) {
  if (max === min) max = min + 1;
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => raw <= s);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

function frame(container, height, margin) {
  container.innerHTML = "";
  const width = Math.max(260, container.clientWidth);
  const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}` }, container);
  return { svg, width, height, inner: { w: width - margin.l - margin.r, h: height - margin.t - margin.b } };
}

/* ------------------------------------------------------------------------ */
/* Line chart (one series) with crosshair hover                              */
/* ------------------------------------------------------------------------ */
/**
 * opts: {
 *   data: [{...}], x: d => label (categorical, evenly spaced),
 *   y: d => number, color, height, yFormat, xTickFormat, xTickEvery,
 *   tooltip: d => [title, rows], onHover: index|null => void
 * }
 * Returns { highlight(index), clear() } so two charts can share a crosshair.
 */
export function lineChart(container, opts) {
  const { data, x, y, color = "var(--series-1)", height = 220, yFormat = String,
          xTickFormat = String, xTickEvery = 3, tooltip, onHover, zeroBased = false } = opts;
  const margin = { t: 12, r: 14, b: 26, l: 46 };
  const { svg, inner } = frame(container, height, margin);
  if (!data.length) return emptyChart(container);

  const values = data.map(y).filter((v) => v != null);
  const ticks = niceTicks(zeroBased ? 0 : Math.min(...values), Math.max(...values));
  const y0 = ticks[0];
  const y1 = ticks[ticks.length - 1];
  const sx = (i) => margin.l + (data.length === 1 ? inner.w / 2 : (i / (data.length - 1)) * inner.w);
  const sy = (v) => margin.t + inner.h - ((v - y0) / (y1 - y0)) * inner.h;

  const grid = el("g", { class: "grid" }, svg);
  for (const t of ticks) {
    el("line", { x1: margin.l, x2: margin.l + inner.w, y1: sy(t), y2: sy(t) }, grid);
    el("text", { x: margin.l - 8, y: sy(t) + 4, "text-anchor": "end" }, svg).textContent = yFormat(t);
  }
  data.forEach((d, i) => {
    if (i % xTickEvery !== 0) return;
    el("text", { x: sx(i), y: height - 6, "text-anchor": "middle" }, svg).textContent = xTickFormat(x(d), i);
  });

  let path = "";
  data.forEach((d, i) => {
    const v = y(d);
    if (v == null) return;
    path += `${path ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`;
  });
  el("path", { d: path, class: "line", stroke: color }, svg);

  // Hover layer: crosshair + dot, hit area = whole plot
  const cross = el("line", { class: "crosshair", y1: margin.t, y2: margin.t + inner.h, visibility: "hidden" }, svg);
  const dot = el("circle", { class: "hover-dot", r: 5, fill: color, visibility: "hidden" }, svg);
  const hit = el("rect", { x: margin.l, y: margin.t, width: inner.w, height: inner.h, fill: "transparent" }, svg);

  const highlight = (i) => {
    const v = y(data[i]);
    cross.setAttribute("x1", sx(i));
    cross.setAttribute("x2", sx(i));
    cross.setAttribute("visibility", "visible");
    if (v != null) {
      dot.setAttribute("cx", sx(i));
      dot.setAttribute("cy", sy(v));
      dot.setAttribute("visibility", "visible");
    }
  };
  const clear = () => {
    cross.setAttribute("visibility", "hidden");
    dot.setAttribute("visibility", "hidden");
  };

  hit.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const px = e.clientX - box.left - margin.l;
    const i = Math.max(0, Math.min(data.length - 1, Math.round((px / inner.w) * (data.length - 1))));
    highlight(i);
    onHover?.(i);
    if (tooltip) showTooltip(e.clientX, e.clientY, ...tooltip(data[i]));
  });
  hit.addEventListener("pointerleave", () => {
    clear();
    onHover?.(null);
    hideTooltip();
  });

  return { highlight, clear };
}

/* ------------------------------------------------------------------------ */
/* Vertical bar chart                                                        */
/* ------------------------------------------------------------------------ */
/**
 * opts: { data, x, y, color: d => css colour, height, yFormat, xTickFormat,
 *         xTickEvery, tooltip, annotate: d => text|null }
 * Bars: 4px rounded tops anchored to the baseline, 2px gap between bars.
 */
export function barChart(container, opts) {
  const { data, x, y, color = () => "var(--series-1)", height = 220, yFormat = String,
          xTickFormat = String, xTickEvery = 1, tooltip, annotate } = opts;
  const margin = { t: 26, r: 8, b: 26, l: 46 };
  const { svg, inner } = frame(container, height, margin);
  if (!data.length) return emptyChart(container);

  const ticks = niceTicks(0, Math.max(...data.map(y)));
  const yMax = ticks[ticks.length - 1];
  const band = inner.w / data.length;
  const gap = Math.min(2, band * 0.2);
  const sy = (v) => margin.t + inner.h - (v / yMax) * inner.h;

  const grid = el("g", { class: "grid" }, svg);
  for (const t of ticks) {
    el("line", { x1: margin.l, x2: margin.l + inner.w, y1: sy(t), y2: sy(t) }, grid);
    el("text", { x: margin.l - 8, y: sy(t) + 4, "text-anchor": "end" }, svg).textContent = yFormat(t);
  }

  const bars = [];
  data.forEach((d, i) => {
    const bx = margin.l + i * band + gap / 2;
    const bw = Math.max(1, band - gap);
    const top = sy(y(d));
    const base = sy(0);
    const r = Math.min(4, bw / 2, base - top);
    // Rounded top corners only; flat on the baseline.
    const dPath = `M${bx},${base} V${top + r} Q${bx},${top} ${bx + r},${top} H${bx + bw - r} ` +
                  `Q${bx + bw},${top} ${bx + bw},${top + r} V${base} Z`;
    const bar = el("path", { d: dPath, class: "bar", fill: color(d) }, svg);
    bars.push(bar);

    // Generous hit target: the full column, not just the bar
    const hit = el("rect", { x: margin.l + i * band, y: margin.t, width: band, height: inner.h, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (e) => {
      bars.forEach((b, j) => b.classList.toggle("dim", j !== i));
      if (tooltip) showTooltip(e.clientX, e.clientY, ...tooltip(d));
    });
    hit.addEventListener("pointerleave", () => {
      bars.forEach((b) => b.classList.remove("dim"));
      hideTooltip();
    });

    if (i % xTickEvery === 0) {
      el("text", { x: bx + bw / 2, y: height - 6, "text-anchor": "middle" }, svg).textContent = xTickFormat(x(d), i);
    }
    // Annotations sit in the top margin with a leader line down to the bar,
    // so they never collide with neighbouring bars.
    const note = annotate?.(d);
    if (note) {
      const cx = bx + bw / 2;
      el("line", { x1: cx, x2: cx, y1: 14, y2: top - 3, class: "crosshair" }, svg);
      const anchor = i < 2 ? "start" : i > data.length - 3 ? "end" : "middle";
      const tx = anchor === "start" ? bx : anchor === "end" ? bx + bw : cx;
      el("text", { x: tx, y: 10, "text-anchor": anchor, class: "annot" }, svg).textContent = note;
    }
  });
  el("line", { class: "baseline", x1: margin.l, x2: margin.l + inner.w, y1: sy(0), y2: sy(0) }, svg);
}

/* ------------------------------------------------------------------------ */
/* Heatmap (HTML grid of buttons, so cells are keyboard-focusable)           */
/* ------------------------------------------------------------------------ */
/**
 * cells: [{ dow, day, hour, value, ... }]
 * opts: { ramp, invert (darker = lower), tooltip: cell => [title, rows], hourLabel }
 */
export function heatmap(container, cells, opts) {
  const { ramp, invert = false, tooltip, hourLabel = String, dayNames } = opts;
  container.innerHTML = "";
  const values = cells.map((c) => c.value).filter((v) => v != null);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const byKey = new Map(cells.map((c) => [`${c.dow}-${c.hour}`, c]));

  const frag = document.createDocumentFragment();
  frag.appendChild(document.createElement("div"));          // corner
  for (let h = 0; h < 24; h++) {
    const label = document.createElement("div");
    label.className = "hm-hour";
    label.textContent = h % 3 === 0 ? hourLabel(h) : "";
    frag.appendChild(label);
  }
  dayNames.forEach((name, dow) => {
    const dayLabel = document.createElement("div");
    dayLabel.className = "hm-day";
    dayLabel.textContent = name;
    frag.appendChild(dayLabel);
    for (let h = 0; h < 24; h++) {
      const cell = byKey.get(`${dow}-${h}`);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "hm-cell";
      if (cell && cell.value != null) {
        let t = max === min ? 0.5 : (cell.value - min) / (max - min);
        if (invert) t = 1 - t;
        btn.style.background = rampColor(ramp, t);
        const [title, rows] = tooltip(cell);
        btn.setAttribute("aria-label", `${title}: ${rows.map((r) => r.join(" ")).join(", ")}`);
        const show = (x, y) => showTooltip(x, y, title, rows);
        btn.addEventListener("pointermove", (e) => show(e.clientX, e.clientY));
        btn.addEventListener("pointerleave", hideTooltip);
        btn.addEventListener("focus", () => {
          const r = btn.getBoundingClientRect();
          show(r.right, r.bottom);
        });
        btn.addEventListener("blur", hideTooltip);
      } else {
        btn.style.background = "var(--no-data)";
        btn.setAttribute("aria-label", `${name} ${hourLabel(h)}: no rides`);
      }
      frag.appendChild(btn);
    }
  });
  container.appendChild(frag);
  return { min, max };
}

/* ------------------------------------------------------------------------ */
/* Legend for a sequential ramp                                              */
/* ------------------------------------------------------------------------ */
export function rampLegend(container, { title, ramp, minLabel, maxLabel, noData }) {
  container.innerHTML =
    `<div class="legend-title">${esc(title)}</div>` +
    `<div class="legend-scale">${ramp.map((c) => `<span style="background:${c}"></span>`).join("")}</div>` +
    `<div class="legend-ticks"><span>${esc(minLabel)}</span><span>${esc(maxLabel)}</span></div>` +
    (noData ? `<div class="legend-nodata"><i></i>${esc(noData)}</div>` : "");
}

/* ------------------------------------------------------------------------ */
/* Horizontal bar list (plain HTML)                                          */
/* ------------------------------------------------------------------------ */
/** items: [{ label, value, display, desc }] */
export function hbars(container, items) {
  const max = Math.max(...items.map((d) => d.value), 1);
  container.innerHTML = items.map((d) => `
    <div class="hbar">
      <span class="hbar-label" title="${esc(d.label)}">${esc(d.label)}</span>
      <span class="hbar-value">${esc(d.display)}</span>
      <span class="hbar-track"><span class="hbar-fill" style="width:${(d.value / max) * 100}%"></span></span>
      ${d.desc ? `<span class="hbar-desc">${esc(d.desc)}</span>` : ""}
    </div>`).join("");
}

function emptyChart(container) {
  container.innerHTML = `<p class="error-note">No rides match these filters.</p>`;
  return { highlight() {}, clear() {} };
}