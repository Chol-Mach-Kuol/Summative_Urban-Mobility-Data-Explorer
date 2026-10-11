from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = BACKEND_DIR / "data" / "raw"
DEFAULT_OUT_DIR = BACKEND_DIR / "data" / "processed"

log = logging.getLogger('pipeline')

MIN_DURATION_MIN = 1.0        
MAX_DURATION_MIN = 6 * 60       
MIN_DISTANCE_MI = 0.01          
MAX_DISTANCE_MI = 100.0         
MAX_SPEED_MPH = 80.0            
MAX_TOTAL_AMOUNT = 1000.0       
MAX_PASSENGERS = 6             


SLOW_SPEED_MPH = 1.0            
HIGH_FARE_PER_MILE = 50.0       
LONG_DURATION_MIN = 3 * 60
TOTAL_MISMATCH_TOLERANCE = 0.10 
UNKNOWN_ZONE_IDS = {264, 265}   

TIME_BUCKETS = [
    ("Morning", 5, 11),     
    ("Afternoon", 12, 16),  
    ("Evening", 17, 20),   
    ("Night", 21, 4),      
]

COLUMN_MAP = {
    "VendorID": "vendor_id",
    "tpep_pickup_datetime": "pickup_datetime",
    "tpep_dropoff_datetime": "dropoff_datetime",
    "passenger_count": "passenger_count",
    "trip_distance": "trip_distance",
    "RatecodeID": "rate_code_id",
    "store_and_fwd_flag": "store_and_fwd_flag",
    "PULocationID": "pickup_location_id",
    "DOLocationID": "dropoff_location_id",
    "payment_type": "payment_type_id",
    "fare_amount": "fare_amount",
    "extra": "extra",
    "mta_tax": "mta_tax",
    "tip_amount": "tip_amount",
    "tolls_amount": "tolls_amount",
    "improvement_surcharge": "improvement_surcharge",
    "total_amount": "total_amount",
    "congestion_surcharge": "congestion_surcharge",
    "Airport_fee": "airport_fee",
    "airport_fee": "airport_fee",
    "cbd_congestion_fee": "cbd_congestion_fee",
}

MONEY_COLS = [
    "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "congestion_surcharge", "airport_fee",
    "cbd_congestion_fee", "total_amount",
]

OPTIONAL_FEE_COLS = ["congestion_surcharge", "airport_fee", "cbd_congestion_fee"]

TOTAL_COMPONENTS = [
    "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "congestion_surcharge", "airport_fee", "cbd_congestion_fee",
]
CRITICAL_COLS = [
    "pickup_datetime", "dropoff_datetime", "pickup_location_id",
    "dropoff_location_id", "trip_distance", "fare_amount", "total_amount",
]
DUPLICATE_KEY = [
    "vendor_id", "pickup_datetime", "dropoff_datetime", "pickup_location_id",
    "dropoff_location_id", "trip_distance", "total_amount",
]

# Code values from the TLC Yellow Trip Record data dictionary
VALID_VENDOR_IDS = {1, 2, 6, 7}
VALID_RATE_CODES = {1, 2, 3, 4, 5, 6, 99}
VALID_PAYMENT_TYPES = {0, 1, 2, 3, 4, 5, 6}
UNKNOWN_RATE_CODE = 99
UNKNOWN_PAYMENT_TYPE = 5

# Columns copied into the exclusion log so each record can be identified and discussed
LOG_CONTEXT_COLS = [
    "pickup_datetime", "dropoff_datetime", "pickup_location_id", "dropoff_location_id",
    "trip_distance", "fare_amount", "total_amount", "passenger_count",
]


# --------------------------------------------------------------------------------------
# Exclusion log
# --------------------------------------------------------------------------------------
@dataclass
class ExclusionLog:
    """Collects every dropped / flagged record together with the rule that caught it."""

    frames: list[pd.DataFrame] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, rows: pd.DataFrame, rule: str, action: str, detail: str) -> None:
        n = len(rows)
        self.counts.setdefault(action, {})
        self.counts[action][rule] = self.counts[action].get(rule, 0) + n
        if n == 0:
            return
        cols = [c for c in LOG_CONTEXT_COLS if c in rows.columns]
        entry = rows[cols].copy()
        entry.insert(0, "source_row", rows["source_row"].to_numpy())
        entry.insert(1, "action", action)
        entry.insert(2, "rule", rule)
        entry.insert(3, "detail", detail)
        self.frames.append(entry)
        log.info("  %-8s %-28s %10s rows  (%s)", action, rule, f"{n:,}", detail)

    def to_frame(self) -> pd.DataFrame:
        if not self.frames:
            return pd.DataFrame(columns=["source_row", "action", "rule", "detail", *LOG_CONTEXT_COLS])
        return pd.concat(self.frames, ignore_index=True)


def _drop(df: pd.DataFrame, mask: pd.Series, rule: str, detail: str, xlog: ExclusionLog) -> pd.DataFrame:
    """Remove rows matching `mask`, logging them under `rule`."""
    mask = mask.fillna(False).astype(bool)
    xlog.record(df.loc[mask], rule, "dropped", detail)
    return df.loc[~mask]


def _flag(df: pd.DataFrame, mask: pd.Series, rule: str, detail: str, xlog: ExclusionLog) -> None:
    """Keep rows matching `mask` but mark them suspicious (in place)."""
    mask = mask.fillna(False).astype(bool)
    if not mask.any():
        xlog.record(df.iloc[0:0], rule, "flagged", detail)
        return
    xlog.record(df.loc[mask], rule, "flagged", detail)
    df.loc[mask, "is_suspicious"] = True
    current = df.loc[mask, "suspicious_reasons"]
    df.loc[mask, "suspicious_reasons"] = np.where(current == "", rule, current + ";" + rule)


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------
def load_trips(path: Path, sample: int | None = None, seed: int = 42) -> pd.DataFrame:
    log.info("Loading trips from %s", path)
    df = pd.read_parquet(path)
    log.info("  %s raw rows, %d columns", f"{len(df):,}", df.shape[1])
    if sample and sample < len(df):
        df = df.sample(n=sample, random_state=seed).sort_index()
        log.info("  sampled down to %s rows", f"{len(df):,}")
    # Keep a pointer back to the raw file row for the exclusion log
    df = df.reset_index(drop=False).rename(columns={"index": "source_row"})
    return df


def load_zone_lookup(path: Path) -> pd.DataFrame:
    log.info("Loading zone lookup from %s", path)
    zones = pd.read_csv(path)
    zones.columns = [c.strip() for c in zones.columns]
    zones = zones.rename(columns={
        "LocationID": "location_id", "Borough": "borough",
        "Zone": "zone_name", "service_zone": "service_zone",
    })
    zones["location_id"] = pd.to_numeric(zones["location_id"], errors="coerce").astype("Int64")
    zones = zones.dropna(subset=["location_id"]).drop_duplicates("location_id")
    for col in ["borough", "zone_name", "service_zone"]:
        zones[col] = (
            zones[col].astype("string").str.strip()
            .replace({"": pd.NA, "N/A": pd.NA, "NV": pd.NA})
            .fillna("Unknown")
        )
    zones["location_id"] = zones["location_id"].astype(int)
    log.info("  %d zones across %d boroughs", len(zones), zones["borough"].nunique())
    return zones.sort_values("location_id").reset_index(drop=True)


def _ring_centroid(ring: list) -> tuple[float, float, float]:
    """Signed area and centroid of one polygon ring (shoelace formula)."""
    pts = np.asarray(ring, dtype=float)[:, :2]
    x, y = pts[:, 0], pts[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    area = cross.sum() / 2.0
    if abs(area) < 1e-12:
        return 0.0, float(x.mean()), float(y.mean())
    cx = ((x + x1) * cross).sum() / (6.0 * area)
    cy = ((y + y1) * cross).sum() / (6.0 * area)
    return area, cx, cy


def _geometry_centroid(geom: dict) -> tuple[float | None, float | None]:
    """Area-weighted centroid of a (Multi)Polygon, using outer rings only."""
    if not geom:
        return None, None
    if geom["type"] == "Polygon":
        polygons = [geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        polygons = geom["coordinates"]
    else:
        return None, None
    total, sx, sy = 0.0, 0.0, 0.0
    for poly in polygons:
        a, cx, cy = _ring_centroid(poly[0])
        total += abs(a)
        sx += abs(a) * cx
        sy += abs(a) * cy
    if total == 0:
        return None, None
    return sx / total, sy / total  # (x=lng, y=lat)


def load_zone_geometries(path: Path) -> tuple[pd.DataFrame, dict[int, dict]]:
    """
    Read the taxi_zones spatial file. Supports GeoJSON directly; shapefiles (.shp / .zip)
    are read with geopandas if it is installed. Returns centroids and raw geometries.
    """
    log.info("Loading zone geometries from %s", path)
    suffix = path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        with open(path, encoding="utf-8") as fh:
            gj = json.load(fh)
        features = gj.get("features", [])
    elif suffix in {".shp", ".zip"}:
        try:
            import geopandas as gpd  # optional dependency
        except ImportError as exc:
            raise RuntimeError("Reading a shapefile needs geopandas; convert it to GeoJSON or `pip install geopandas`.") from exc
        gdf = gpd.read_file(path).to_crs(epsg=4326)  # TLC shapefile is in NY State Plane feet
        features = json.loads(gdf.to_json())["features"]
    else:
        raise ValueError(f"Unsupported spatial file type: {path}")

    rows, geometries = [], {}
    for feat in features:
        props = {k.lower(): v for k, v in (feat.get("properties") or {}).items()}
        loc = props.get("locationid", props.get("location_id", props.get("objectid")))
        try:
            loc = int(float(loc))
        except (TypeError, ValueError):
            continue
        geom = feat.get("geometry")
        lng, lat = _geometry_centroid(geom)
        # Zones 56/103 appear twice in the TLC file (split polygons): merge into a MultiPolygon
        if loc in geometries and geom:
            prev = geometries[loc]
            polys = (prev["coordinates"] if prev["type"] == "MultiPolygon" else [prev["coordinates"]]) + \
                    (geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]])
            geometries[loc] = {"type": "MultiPolygon", "coordinates": polys}
            lng, lat = _geometry_centroid(geometries[loc])
            rows = [r for r in rows if r["location_id"] != loc]
        elif geom:
            geometries[loc] = geom
        rows.append({"location_id": loc, "centroid_lng": lng, "centroid_lat": lat})

    cent = pd.DataFrame(rows, columns=["location_id", "centroid_lng", "centroid_lat"])
    # Warn if coordinates are clearly not WGS84 (e.g. raw state-plane feet in a GeoJSON)
    if len(cent) and cent["centroid_lat"].abs().max() > 90:
        log.warning("  geometry coordinates are not lat/lng (projected CRS?) - centroids kept as-is")
    log.info("  %d zone geometries loaded", len(geometries))
    return cent, geometries


# --------------------------------------------------------------------------------------
# Cleaning steps
# --------------------------------------------------------------------------------------
def normalise_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Rename to snake_case, coerce types, round numerics, standardise categoricals."""
    df = df.rename(columns={c: COLUMN_MAP[c] for c in df.columns if c in COLUMN_MAP})
    for col in OPTIONAL_FEE_COLS:
        if col not in df.columns:
            df[col] = 0.0

    # Timestamps: naive NYC local time (as published by TLC), truncated to whole seconds
    for col in ["pickup_datetime", "dropoff_datetime"]:
        ts = pd.to_datetime(df[col], errors="coerce")
        if getattr(ts.dt, "tz", None) is not None:
            ts = ts.dt.tz_convert("America/New_York").dt.tz_localize(None)
        df[col] = ts.dt.floor("s")

    # Numerics
    df["trip_distance"] = pd.to_numeric(df["trip_distance"], errors="coerce")
    for col in MONEY_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["vendor_id", "passenger_count", "rate_code_id", "pickup_location_id",
                "dropoff_location_id", "payment_type_id"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").round().astype("Int64")

    # store_and_fwd_flag: Y / N, anything else -> U (unknown)
    flag = df["store_and_fwd_flag"].astype("string").str.strip().str.upper()
    df["store_and_fwd_flag"] = flag.where(flag.isin(["Y", "N"]), "U").fillna("U")

    keep = ["source_row"] + list(dict.fromkeys(COLUMN_MAP.values()))
    return df[[c for c in keep if c in df.columns]]


def handle_missing(df: pd.DataFrame, xlog: ExclusionLog) -> pd.DataFrame:
    log.info("Missing values")
    missing = df[CRITICAL_COLS].isna().any(axis=1)
    df = _drop(df, missing, "missing_critical_field",
               "null timestamp, location, distance or fare", xlog)

    
    for col in OPTIONAL_FEE_COLS:
        df[col] = df[col].fillna(0.0)
    for col in ["extra", "mta_tax", "tip_amount", "tolls_amount", "improvement_surcharge"]:
        df[col] = df[col].fillna(0.0)

   
    df["rate_code_id"] = df["rate_code_id"].where(df["rate_code_id"].isin(VALID_RATE_CODES), UNKNOWN_RATE_CODE)
    df["payment_type_id"] = df["payment_type_id"].where(df["payment_type_id"].isin(VALID_PAYMENT_TYPES), UNKNOWN_PAYMENT_TYPE)
    df["rate_code_id"] = df["rate_code_id"].fillna(UNKNOWN_RATE_CODE).astype("Int64")
    df["payment_type_id"] = df["payment_type_id"].fillna(UNKNOWN_PAYMENT_TYPE).astype("Int64")
    # passenger_count stays nullable: unknown is more honest than an imputed 1
    return df


def handle_duplicates(df: pd.DataFrame, xlog: ExclusionLog) -> pd.DataFrame:
    log.info("Duplicates")
    dup = df.duplicated(subset=DUPLICATE_KEY, keep="first")
    return _drop(df, dup, "duplicate_trip", "same vendor, timestamps, zones, distance and total", xlog)


def infer_period(df: pd.DataFrame, period: str | None) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Data period = given YYYY-MM, else the most common pickup month in the file."""
    if period:
        start = pd.Timestamp(f"{period}-01")
    else:
        months = df["pickup_datetime"].dt.to_period("M").value_counts()
        start = months.idxmax().to_timestamp()
    end = start + pd.offsets.MonthBegin(1)
    return start, end


def handle_temporal(df: pd.DataFrame, xlog: ExclusionLog, period: str | None) -> pd.DataFrame:
    log.info("Temporal checks")
    start, end = infer_period(df, period)
    log.info("  data period: %s to %s", start.date(), (end - pd.Timedelta(days=1)).date())
    out_of_period = (df["pickup_datetime"] < start) | (df["pickup_datetime"] >= end)
    df = _drop(df, out_of_period, "pickup_outside_period",
               f"pickup not in {start:%Y-%m}", xlog)

    duration = (df["dropoff_datetime"] - df["pickup_datetime"]).dt.total_seconds() / 60.0
    df = df.assign(trip_duration_min=duration.round(2))
    df = _drop(df, df["trip_duration_min"] <= 0, "dropoff_not_after_pickup",
               "dropoff at or before pickup", xlog)
    df = _drop(df, df["trip_duration_min"] < MIN_DURATION_MIN, "duration_too_short",
               f"< {MIN_DURATION_MIN:g} min", xlog)
    df = _drop(df, df["trip_duration_min"] > MAX_DURATION_MIN, "duration_too_long",
               f"> {MAX_DURATION_MIN / 60:g} h", xlog)
    return df


def handle_distance_and_fares(df: pd.DataFrame, xlog: ExclusionLog) -> pd.DataFrame:
    log.info("Distance and fare checks")
    df = _drop(df, df["trip_distance"] < MIN_DISTANCE_MI, "distance_zero_or_negative",
               f"< {MIN_DISTANCE_MI} mi", xlog)
    df = _drop(df, df["trip_distance"] > MAX_DISTANCE_MI, "distance_implausible",
               f"> {MAX_DISTANCE_MI:g} mi", xlog)

    negative_component = (df[MONEY_COLS] < 0).any(axis=1)
    df = _drop(df, negative_component, "negative_fare_component",
               "negative fare/surcharge/total (refunds, voids, reversals)", xlog)
    df = _drop(df, df["fare_amount"] <= 0, "zero_fare", "fare_amount = 0", xlog)
    df = _drop(df, df["total_amount"] > MAX_TOTAL_AMOUNT, "total_implausible",
               f"total > ${MAX_TOTAL_AMOUNT:,.0f}", xlog)
    return df


def handle_locations(df: pd.DataFrame, zones: pd.DataFrame, xlog: ExclusionLog) -> pd.DataFrame:
    log.info("Zone integrity checks")
    valid = set(zones["location_id"])
    bad = ~df["pickup_location_id"].isin(valid) | ~df["dropoff_location_id"].isin(valid)
    return _drop(df, bad, "unknown_location_id", "PU/DO LocationID not in taxi_zone_lookup", xlog)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derived features (see module docstring for definitions)."""
    log.info("Feature engineering")
    hours = df["trip_duration_min"] / 60.0
    df["trip_speed_mph"] = (df["trip_distance"] / hours).round(2)
    df["fare_per_mile"] = (df["total_amount"] / df["trip_distance"]).round(2)
    df["tip_pct"] = np.where(df["fare_amount"] > 0,
                             (df["tip_amount"] / df["fare_amount"] * 100).round(2), np.nan)

    hour = df["pickup_datetime"].dt.hour
    df["pickup_hour"] = hour.astype("int8")
    df["pickup_dow"] = df["pickup_datetime"].dt.dayofweek.astype("int8")   # 0 = Monday
    df["pickup_date"] = df["pickup_datetime"].dt.normalize()
    df["is_weekend"] = df["pickup_dow"] >= 5
    df["time_of_day_bucket"] = time_of_day_bucket(hour)
    return df


def time_of_day_bucket(hour: pd.Series) -> pd.Series:
    conditions, labels = [], []
    for label, lo, hi in TIME_BUCKETS:
        conditions.append(hour.between(lo, hi) if lo <= hi else (hour >= lo) | (hour <= hi))
        labels.append(label)
    return pd.Series(np.select(conditions, labels, default="Night"), index=hour.index, dtype="string")


def handle_physical_outliers(df: pd.DataFrame, xlog: ExclusionLog) -> pd.DataFrame:
    log.info("Physical outliers (needs derived speed)")
    return _drop(df, df["trip_speed_mph"] > MAX_SPEED_MPH, "speed_implausible",
                 f"average speed > {MAX_SPEED_MPH:g} mph", xlog)


def flag_suspicious(df: pd.DataFrame, xlog: ExclusionLog) -> pd.DataFrame:
    """Plausible-but-odd records: kept in the dataset, marked for analysts."""
    log.info("Suspicious (kept, flagged)")
    df = df.copy()
    df["is_suspicious"] = False
    df["suspicious_reasons"] = ""

    pc = df["passenger_count"]
    _flag(df, pc.isna(), "passenger_count_missing", "passenger_count null", xlog)
    bad_pc = pc.notna() & ((pc == 0) | (pc > MAX_PASSENGERS))
    _flag(df, bad_pc, "passenger_count_invalid", f"0 or > {MAX_PASSENGERS} passengers -> set to null", xlog)
    df.loc[bad_pc.fillna(False), "passenger_count"] = pd.NA

    _flag(df, df["trip_speed_mph"] < SLOW_SPEED_MPH, "speed_very_slow",
          f"< {SLOW_SPEED_MPH:g} mph (meter left running?)", xlog)
    _flag(df, df["trip_duration_min"] > LONG_DURATION_MIN, "duration_long",
          f"> {LONG_DURATION_MIN / 60:g} h", xlog)
    _flag(df, df["fare_per_mile"] > HIGH_FARE_PER_MILE, "fare_per_mile_high",
          f"> ${HIGH_FARE_PER_MILE:g}/mile", xlog)
    unknown_zone = df["pickup_location_id"].isin(UNKNOWN_ZONE_IDS) | df["dropoff_location_id"].isin(UNKNOWN_ZONE_IDS)
    _flag(df, unknown_zone, "zone_unknown_or_outside_nyc", "LocationID 264/265", xlog)
    mismatch = (df[TOTAL_COMPONENTS].sum(axis=1) - df["total_amount"]).abs() > TOTAL_MISMATCH_TOLERANCE
    _flag(df, mismatch, "total_mismatch",
          f"fare components differ from total by > ${TOTAL_MISMATCH_TOLERANCE:.2f}", xlog)
    _flag(df, ~df["vendor_id"].isin(VALID_VENDOR_IDS), "vendor_unknown", "VendorID not in data dictionary", xlog)
    _flag(df, df["rate_code_id"] == UNKNOWN_RATE_CODE, "rate_code_unknown",
          "RatecodeID null / invalid -> 99 (unknown)", xlog)
    return df


def finalise(df: pd.DataFrame) -> pd.DataFrame:
    """Final rounding and column order for storage."""
    for col in MONEY_COLS:
        df[col] = df[col].round(2)
    df["trip_distance"] = df["trip_distance"].round(2)
    order = [
        "source_row", "vendor_id", "pickup_datetime", "dropoff_datetime",
        "pickup_location_id", "dropoff_location_id", "passenger_count", "trip_distance",
        "rate_code_id", "store_and_fwd_flag", "payment_type_id", *MONEY_COLS,
        "trip_duration_min", "trip_speed_mph", "fare_per_mile", "tip_pct",
        "time_of_day_bucket", "pickup_hour", "pickup_dow", "pickup_date", "is_weekend",
        "is_suspicious", "suspicious_reasons",
    ]
    return df[order].sort_values("pickup_datetime").reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def run_pipeline(
    trips_path: Path,
    zones_path: Path,
    geo_path: Path | None = None,
    out_dir: Path = DEFAULT_OUT_DIR,
    sample: int | None = None,
    period: str | None = None,
) -> dict:
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    xlog = ExclusionLog()

    zones = load_zone_lookup(zones_path)
    geometries: dict[int, dict] = {}
    if geo_path:
        centroids, geometries = load_zone_geometries(geo_path)
        zones = zones.merge(centroids, on="location_id", how="left")
        missing_geo = zones.loc[zones["centroid_lat"].isna(), "location_id"].tolist()
        if missing_geo:
            log.info("  zones without geometry (expected for 264/265): %s", missing_geo)
    else:
        zones["centroid_lng"] = np.nan
        zones["centroid_lat"] = np.nan

    raw = load_trips(trips_path, sample=sample)
    n_raw=len(raw)

    df = normalise_schema(raw)
    del raw
    df = handle_missing(df, xlog)
    df = handle_duplicates(df, xlog)
    df = handle_temporal(df, xlog, period)
    df = handle_distance_and_fares(df, xlog)
    df = handle_locations(df, zones, xlog)
    df = engineer_features(df)
    df = handle_physical_outliers(df, xlog)
    df = flag_suspicious(df, xlog)
    df = finalise(df)

    # ---- write outputs ----
    trips_out = out_dir / "trips_clean.parquet"
    df.to_parquet(trips_out, index=False)
    zones.to_csv(out_dir / "zones_clean.csv", index=False)
    if geometries:
        with open(out_dir / "zone_geometries.json", "w", encoding="utf-8") as fh:
            json.dump({str(k): v for k, v in geometries.items()}, fh)
    xframe = xlog.to_frame()
    xframe.to_csv(out_dir / "exclusion_log.csv", index=False)

    dropped = sum(xlog.counts.get("dropped", {}).values())
    report = {
        "run_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "inputs": {"trips": str(trips_path), "zones": str(zones_path),
                   "geo": str(geo_path) if geo_path else None, "sample": sample},
        "rows_raw": n_raw,
        "rows_clean": len(df),
        "rows_dropped": dropped,
        "rows_flagged_suspicious": int(df["is_suspicious"].sum()),
        "pct_retained": round(len(df) / n_raw * 100, 2) if n_raw else 0.0,
        "dropped_by_rule": xlog.counts.get("dropped", {}),
        "flagged_by_rule": xlog.counts.get("flagged", {}),
        "thresholds": {
            "min_duration_min": MIN_DURATION_MIN, "max_duration_min": MAX_DURATION_MIN,
            "min_distance_mi": MIN_DISTANCE_MI, "max_distance_mi": MAX_DISTANCE_MI,
            "max_speed_mph": MAX_SPEED_MPH, "max_total_amount": MAX_TOTAL_AMOUNT,
            "slow_speed_mph": SLOW_SPEED_MPH, "high_fare_per_mile": HIGH_FARE_PER_MILE,
        },
        "time_of_day_buckets": {label: f"{lo:02d}:00-{hi:02d}:59" for label, lo, hi in TIME_BUCKETS},
        "feature_summary": {
            col: {k: (None if pd.isna(v) else round(float(v), 2))
                  for k, v in df[col].describe(percentiles=[0.5]).items() if k != "count"}
            for col in ["trip_duration_min", "trip_speed_mph", "fare_per_mile", "tip_pct"]
        } if len(df) else {},
        "time_of_day_counts": df["time_of_day_bucket"].value_counts().to_dict() if len(df) else {},
        "outputs": {"trips": str(trips_out), "exclusion_log": str(out_dir / "exclusion_log.csv")},
        "elapsed_sec": round(time.time() - t0, 1),
    }
    with open(out_dir / "cleaning_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    log.info("Done: %s raw -> %s clean (%.2f%% kept), %s dropped, %s flagged, %.1fs",
             f"{n_raw:,}", f"{len(df):,}", report["pct_retained"], f"{dropped:,}",
             f"{report['rows_flagged_suspicious']:,}", report["elapsed_sec"])
    return report


def _first_match(directory: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        hits = sorted(directory.glob(pattern))
        if hits:
            return hits[0]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean and enrich NYC yellow taxi trip data.")
    parser.add_argument("--trips", type=Path, help="yellow_tripdata .parquet file (default: first one in data/raw)")
    parser.add_argument("--zones", type=Path, help="taxi_zone_lookup.csv (default: data/raw)")
    parser.add_argument("--geo", type=Path, help="taxi_zones .geojson/.json (optional)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument("--sample", type=int, help="randomly sample N trips (for development)")
    parser.add_argument("--period", help="expected data month YYYY-MM (default: inferred)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    trips = args.trips or _first_match(DEFAULT_RAW_DIR, ["yellow_tripdata*.parquet", "*.parquet"])
    zones = args.zones or _first_match(DEFAULT_RAW_DIR, ["taxi_zone_lookup*.csv", "*zone*.csv"])
    geo = args.geo or _first_match(DEFAULT_RAW_DIR, ["taxi_zones*.geojson", "taxi_zones*.json"])
    if not trips or not zones:
        parser.error(f"trip parquet and zone lookup CSV are required (looked in {DEFAULT_RAW_DIR})")

    run_pipeline(trips, zones, geo, args.out, args.sample, args.period)


if __name__ == "__main__":
    main()