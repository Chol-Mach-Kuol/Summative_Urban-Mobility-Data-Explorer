/**
 * charts.js — Chol Mach Kuol
 * SVG chart primitives used by main.js.
 * No external libraries — hand-drawn SVG only.
 */

export const BLUE_RAMP   = ["#e8f4fd","#bdd7ee","#6baed6","#2171b5","#08306b"];
export const ORANGE_RAMP = ["#feedde","#fdbe85","#fd8d3c","#e6550d","#a63603"];

/* -------------------------------------------------------------------------
 * Shared tooltip
 * ------------------------------------------------------------------------- */
const tip = document.getElementById("tooltip");
let tipVisible = false;

function showTip(e, title, rows) {
  if (!tip) return;
  tip.hidden = false;
  tipVisible = true;
  tip.innerHTML = `<strong>${title}</strong>` +
    rows.map(([k, v]) => `<div class="tip-row"><span>${k}</span><span>${v}</span></div>`).join("");
  moveTip(e);
}

function moveTip(e) {
  if (!tip || !tipVisible) return;
  const x = e.clientX + 14;
  const y = e.clientY - 28;
  tip.style.left = `${Math.min(x, window.innerWidth - tip.offsetWidth - 8)}px`;
  tip.style.top  = `${Math.max(y, 4)}px`;
}

function hideTip() {
  if (!tip) return;
  tip.hidden = true;
  tipVisible = false;
}

/* -------------------------------------------------------------------------
 * Colour scale helpers
 * ------------------------------------------------------------------------- */
function colorScale(value, min, max, ramp, invert = false) {
  if (value == null || max === min) return ramp[0];
  let t = (value - min) / (max - min);
  if (invert) t = 1 - t;
  const i = Math.min(Math.floor(t * (ramp.length - 1)), ramp.length - 2);
  return ramp[i];
}

/* -------------------------------------------------------------------------
 * rampLegend
 * ------------------------------------------------------------------------- */
export function rampLegend(el, { title, ramp, minLabel, maxLabel }) {
  if (!el) return;
  el.innerHTML = `
    <span class="legend-label">${minLabel}</span>
    <span class="legend-swatch" style="background:linear-gradient(to right,${ramp.join(",")})"></span>
    <span class="legend-label">${maxLabel}</span>
    <span class="legend-title">${title}</span>`;
}

/* -------------------------------------------------------------------------
 * hbars — horizontal bar chart (used for zone destinations + data quality)
 * ------------------------------------------------------------------------- */
export function hbars(el, items) {
  if (!el || !items.length) return;
  const max = Math.max(...items.map(d => d.value));
  el.innerHTML = items.map(({ label, value, display }) => `
    <div class="hbar-row">
      <span class="hbar-label" title="${label}">${label}</span>
      <span class="hbar-track"><span class="hbar-fill" style="width:${max ? (value / max * 100).toFixed(1) : 0}%"></span></span>
      <span class="hbar-value">${display ?? value}</span>
    </div>`).join("");
}

/* -------------------------------------------------------------------------
 * lineChart — returns { clear, highlight } for crosshair sync
 * ------------------------------------------------------------------------- */
export function lineChart(el, { data, x, y, color, height = 210, zeroBased = true,
  xTickFormat, xTickEvery = 1, yFormat, tooltip, onHover }) {
  if (!el || !data?.length) return { clear: () => {}, highlight: () => {} };

  const W = el.clientWidth || 400;
  const H = height;
  const pad = { top: 12, right: 16, bottom: 32, left: 44 };
  const iw = W - pad.left - pad.right;
  const ih = H - pad.top - pad.bottom;

  const xs = data.map(x);
  const ys = data.map(y).filter(v => v != null);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = zeroBased ? 0 : Math.min(...ys);
  const yMax = Math.max(...ys);

  const px = v => pad.left + ((v - xMin) / (xMax - xMin || 1)) * iw;
  const py = v => pad.top + ih - ((v - yMin) / (yMax - yMin || 1)) * ih;

  const pts = data.map(d => `${px(x(d))},${py(y(d) ?? yMin)}`).join(" ");

  // y-axis ticks
  const yTicks = 4;
  const yTickLines = Array.from({ length: yTicks + 1 }, (_, i) => {
    const v = yMin + (yMax - yMin) * (i / yTicks);
    const cy = py(v);
    return `<line x1="${pad.left}" x2="${W - pad.right}" y1="${cy}" y2="${cy}" stroke="var(--border)" stroke-dasharray="3 3"/>
            <text x="${pad.left - 4}" y="${cy + 4}" text-anchor="end" font-size="10" fill="var(--text-muted)">${yFormat ? yFormat(+v.toFixed(1)) : +v.toFixed(1)}</text>`;
  }).join("");

  // x-axis ticks
  const xTickLines = data.filter((_, i) => i % xTickEvery === 0).map(d => {
    const cx = px(x(d));
    return `<text x="${cx}" y="${H - 4}" text-anchor="middle" font-size="10" fill="var(--text-muted)">${xTickFormat ? xTickFormat(x(d)) : x(d)}</text>`;
  }).join("");

  const svgId = `lc-${Math.random().toString(36).slice(2)}`;
  el.innerHTML = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" class="line-chart">
    ${yTickLines}
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
    ${data.map((d, i) => `<circle cx="${px(x(d))}" cy="${py(y(d) ?? yMin)}" r="3" fill="${color}" opacity="0"
      class="lc-dot" data-i="${i}"/>`).join("")}
    ${xTickLines}
    <line id="${svgId}-hl" x1="0" x2="0" y1="${pad.top}" y2="${H - pad.bottom}" stroke="var(--text-muted)" stroke-width="1" stroke-dasharray="4 2" opacity="0"/>
  </svg>`;

  const svg = el.querySelector("svg");
  const hlLine = el.querySelector(`#${svgId}-hl`);

  function highlight(i) {
    const d = data[i];
    if (!d) return;
    hlLine.setAttribute("x1", px(x(d)));
    hlLine.setAttribute("x2", px(x(d)));
    hlLine.setAttribute("opacity", "1");
  }
  function clear() { hlLine.setAttribute("opacity", "0"); hideTip(); }

  svg.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const mx = e.clientX - rect.left - pad.left;
    const i = Math.round((mx / iw) * (data.length - 1));
    const idx = Math.max(0, Math.min(data.length - 1, i));
    highlight(idx);
    onHover?.(idx);
    if (tooltip) {
      const [title, rows] = tooltip(data[idx]);
      showTip(e, title, rows);
    }
  });
  svg.addEventListener("mouseleave", () => { clear(); onHover?.(null); });
  svg.addEventListener("mousemove", moveTip);

  return { clear, highlight };
}

/* -------------------------------------------------------------------------
 * barChart — vertical bars (daily rides)
 * ------------------------------------------------------------------------- */
export function barChart(el, { data, x, y, color, height = 230,
  yFormat, xTickFormat, xTickEvery = 1, annotate, tooltip }) {
  if (!el || !data?.length) return;

  const W = el.clientWidth || 600;
  const H = height;
  const pad = { top: 24, right: 8, bottom: 32, left: 44 };
  const iw = W - pad.left - pad.right;
  const ih = H - pad.top - pad.bottom;

  const ys = data.map(y);
  const yMax = Math.max(...ys);
  const barW = Math.max(1, iw / data.length - 1);

  const py = v => ih - (v / (yMax || 1)) * ih;

  const bars = data.map((d, i) => {
    const bx = pad.left + (i / data.length) * iw;
    const bh = (y(d) / (yMax || 1)) * ih;
    const by = pad.top + ih - bh;
    const ann = annotate?.(d);
    return `<rect x="${bx}" y="${by}" width="${barW}" height="${bh}" fill="${color(d)}" rx="1"
              class="bar" data-i="${i}"/>
            ${ann ? `<text x="${bx + barW / 2}" y="${by - 4}" text-anchor="middle" font-size="9" fill="var(--text-muted)">${ann}</text>` : ""}`;
  }).join("");

  const yTicks = Array.from({ length: 4 }, (_, i) => {
    const v = (yMax / 4) * (i + 1);
    const cy = pad.top + py(v);
    return `<line x1="${pad.left}" x2="${W - pad.right}" y1="${cy}" y2="${cy}" stroke="var(--border)" stroke-dasharray="3 3"/>
            <text x="${pad.left - 4}" y="${cy + 4}" text-anchor="end" font-size="10" fill="var(--text-muted)">${yFormat ? yFormat(v) : Math.round(v)}</text>`;
  }).join("");

  const xTicks = data.filter((_, i) => i % xTickEvery === 0).map((d, _, arr) => {
    const i = data.indexOf(d);
    const bx = pad.left + (i / data.length) * iw + barW / 2;
    return `<text x="${bx}" y="${H - 4}" text-anchor="middle" font-size="10" fill="var(--text-muted)">${xTickFormat ? xTickFormat(x(d)) : x(d)}</text>`;
  }).join("");

  el.innerHTML = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" class="bar-chart">
    ${yTicks}${bars}${xTicks}
  </svg>`;

  el.querySelectorAll(".bar").forEach((rect, i) => {
    rect.addEventListener("mouseenter", (e) => {
      if (tooltip) { const [title, rows] = tooltip(data[i]); showTip(e, title, rows); }
    });
    rect.addEventListener("mousemove", moveTip);
    rect.addEventListener("mouseleave", hideTip);
  });
}

/* -------------------------------------------------------------------------
 * heatmap — weekday × hour grid
 * ------------------------------------------------------------------------- */
export function heatmap(el, cells, { ramp, invert, dayNames, hourLabel, tooltip }) {
  if (!el || !cells.length) return { min: 0, max: 0 };

  const vals = cells.map(c => c.value).filter(v => v != null);
  const min = Math.min(...vals);
  const max = Math.max(...vals);

  const DAYS = 7, HOURS = 24;
  const cellW = Math.floor((el.clientWidth || 700) / HOURS);
  const cellH = 28;
  const labelW = 36;
  const W = labelW + HOURS * cellW;
  const H = DAYS * cellH;

  const lookup = new Map(cells.map(c => [`${c.dow}-${c.hour}`, c]));

  const rects = [];
  for (let d = 0; d < DAYS; d++) {
    for (let h = 0; h < HOURS; h++) {
      const c = lookup.get(`${d}-${h}`);
      const fill = c ? colorScale(c.value, min, max, ramp, invert) : "var(--surface-2)";
      rects.push(`<rect x="${labelW + h * cellW}" y="${d * cellH}" width="${cellW - 1}" height="${cellH - 1}"
        fill="${fill}" rx="1" class="hm-cell" data-d="${d}" data-h="${h}"/>`);
    }
  }

  const dayLabels = dayNames.map((name, d) =>
    `<text x="${labelW - 4}" y="${d * cellH + cellH / 2 + 4}" text-anchor="end" font-size="11" fill="var(--text-muted)">${name}</text>`
  ).join("");

  el.innerHTML = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" class="heatmap-svg">
    ${dayLabels}${rects.join("")}
  </svg>`;

  el.querySelectorAll(".hm-cell").forEach(rect => {
    const d = Number(rect.dataset.d), h = Number(rect.dataset.h);
    const c = lookup.get(`${d}-${h}`);
    if (!c || !tooltip) return;
    rect.addEventListener("mouseenter", (e) => { const [title, rows] = tooltip(c); showTip(e, title, rows); });
    rect.addEventListener("mousemove", moveTip);
    rect.addEventListener("mouseleave", hideTip);
  });

  return { min, max };
}
