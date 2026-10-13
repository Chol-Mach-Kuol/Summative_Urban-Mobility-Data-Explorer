/**
 * api.js - talking to the Flask backend.
 *
 * Every request carries the current filters as URL parameters, e.g.
 *   /api/summary?borough_id=4&hour_min=7&hour_max=9
 * Empty filters are left out so the backend can use its fast summary tables.
 */

export class ApiError extends Error {}

/** Turn a filter object into "?a=1&b=2", skipping empty values. */
export function toQuery(filters = {}, extra = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...filters, ...extra })) {
    if (value === "" || value === null || value === undefined || value === false) continue;
    params.set(key, value === true ? "1" : String(value));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/**
 * GET a JSON endpoint. Returns { data, ms } where ms is the server's own
 * timing (X-Query-Time-ms header), shown on the meter.
 * Older requests for the same "channel" are cancelled, so fast clicking on
 * filters never lets a slow, stale answer overwrite a newer one.
 */
const inFlight = new Map();

export async function get(path, filters, extra, channel = path) {
  inFlight.get(channel)?.abort();
  const controller = new AbortController();
  inFlight.set(channel, controller);

  let response;
  try {
    response = await fetch(`/api/${path}${toQuery(filters, extra)}`, { signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("Can't reach the server. Check that backend/app.py is running.");
  } finally {
    if (inFlight.get(channel) === controller) inFlight.delete(channel);
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(body.error || `The server answered ${response.status}.`);
  return { data: body, ms: Number(response.headers.get("X-Query-Time-ms")) };
}

/* ------------------------------------------------------------------------ */
/* Number formatting                                                         */
/* ------------------------------------------------------------------------ */
const intFmt = new Intl.NumberFormat("en-US");

export const fmt = {
  int: (v) => (v == null ? "–" : intFmt.format(Math.round(v))),
  compact: (v) => {
    if (v == null) return "–";
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(v >= 1e7 ? 1 : 2)}M`;
    if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}k`;
    return String(Math.round(v));
  },
  money: (v) => (v == null ? "–" : `$${v.toFixed(2)}`),
  money0: (v) => (v == null ? "–" : `$${Math.round(v)}`),
  mph: (v) => (v == null ? "–" : `${v.toFixed(1)} mph`),
  miles: (v) => (v == null ? "–" : `${v.toFixed(2)} mi`),
  minutes: (v) => (v == null ? "–" : `${v.toFixed(1)} min`),
  pct: (v) => (v == null ? "–" : `${v.toFixed(1)}%`),
  hour: (h) => (h === 0 ? "12 am" : h < 12 ? `${h} am` : h === 12 ? "12 pm" : `${h - 12} pm`),
  hourShort: (h) => (h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`),
  date: (iso) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }),
  datetime: (s) => {
    const d = new Date(s.replace(" ", "T"));
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  },
};

/** Escape text before putting it inside innerHTML. */
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}