# Algorithm Notes — Chol Mach Kuol

## 1. Top Routes (`get_top_routes`)

**What it does:**
Aggregate all trips by pickup borough and dropoff borough pair, counts how many trips
occured on each pair, and returns the top N ranked by trip count.

**Approach:**
- SQLite GROUP BY acts as a hash map aggregation — each unique (pu_borough, do_borough)
  pair is a key, trip count is the value.
- Results are sorted descending by trip count (ORDER BY ... DESC).

**Time complexity:**
- O(n) to scan all trips
- O(k log k) to sort where k = unique borough pairs (NYC has 5 boroughs → max 25 pairs)
- Overall: O(n) dominant

**Why this approach:**
Borough-level grouping keeps k tiny (≤ 25), so sorting is essentially constant.
A full zone-level approach would have k ≈ 63,000 pairs — borough level is the right granularity for a top-routes insight.

---

## 2. Zone Detail (`get_zone_detail`)

**What it does:**
For a single zone ID, returns the zone metadata (name, borough) joined with aggregated
trip stats — total trips, average fare, average speed — for trips that originated there.

**Approach:**
- LEFT JOIN ensures zones with zero trips still return a result (total_trips = 0).
- Single-row lookup on zone_id (primary key) + aggregation over matching trips.

**Time complexity:**
- O(1) zone lookup (primary key index)
- O(m) aggregation where m = trips from that zone
- Overall: O(m)

**Why this approach:**
A zone detail view is always a single-zone query, so there's no need to pre-compute
or cache — a direct indexed query is fast enough at this data scale.
