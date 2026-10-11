from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pymysql

BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_PROCESSED_DIR = BACKEND_DIR / "data" / "processed"
READ_BATCH = 50_000      # rows read from parquet at a time
INSERT_CHUNK = 5_000     # rows per multi-row INSERT (stays well under max_allowed_packet)

log = logging.getLogger("insert_data")

try:  # optional: read credentials from backend/.env
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass

# Lookup values from the TLC Yellow Trip Record data dictionary
VENDORS = {
    1: "Creative Mobile Technologies, LLC",
    2: "Curb Mobility, LLC",
    6: "Myle Technologies Inc",
    7: "Helix",
}
RATE_CODES = {
    1: "Standard rate", 2: "JFK", 3: "Newark", 4: "Nassau or Westchester",
    5: "Negotiated fare", 6: "Group ride", 99: "Unknown",
}
PAYMENT_TYPES = {
    0: "Flex Fare trip", 1: "Credit card", 2: "Cash", 3: "No charge",
    4: "Dispute", 5: "Unknown", 6: "Voided trip",
}

# Dropped children first so foreign keys never block a rebuild
ALL_TABLES = ["exclusion_log", "pipeline_runs", "trips", "zones", "boroughs",
              "service_zones", "vendors", "rate_codes", "payment_types"]

TABLE_OPTIONS = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

SCHEMA = [
    f"""
    CREATE TABLE IF NOT EXISTS boroughs (
        borough_id  TINYINT UNSIGNED PRIMARY KEY,
        name        VARCHAR(50) NOT NULL UNIQUE
    ) {TABLE_OPTIONS}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS service_zones (
        service_zone_id TINYINT UNSIGNED PRIMARY KEY,
        name            VARCHAR(50) NOT NULL UNIQUE
    ) {TABLE_OPTIONS}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS zones (
        location_id      SMALLINT UNSIGNED PRIMARY KEY,
        zone_name        VARCHAR(100) NOT NULL,
        borough_id       TINYINT UNSIGNED NOT NULL,
        service_zone_id  TINYINT UNSIGNED NOT NULL,
        centroid_lat     DECIMAL(9,6) NULL,
        centroid_lng     DECIMAL(9,6) NULL,
        geometry_geojson LONGTEXT NULL,
        CONSTRAINT fk_zones_borough FOREIGN KEY (borough_id) REFERENCES boroughs(borough_id),
        CONSTRAINT fk_zones_service FOREIGN KEY (service_zone_id) REFERENCES service_zones(service_zone_id),
        INDEX idx_zones_borough (borough_id)
    ) {TABLE_OPTIONS}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS vendors (
        vendor_id   TINYINT UNSIGNED PRIMARY KEY,
        name        VARCHAR(100) NOT NULL
    ) {TABLE_OPTIONS}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS rate_codes (
        rate_code_id TINYINT UNSIGNED PRIMARY KEY,
        description  VARCHAR(50) NOT NULL
    ) {TABLE_OPTIONS}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS payment_types (
        payment_type_id TINYINT UNSIGNED PRIMARY KEY,
        description     VARCHAR(50) NOT NULL
    ) {TABLE_OPTIONS}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS trips (
        trip_id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        source_row             INT UNSIGNED NULL,
        vendor_id              TINYINT UNSIGNED NULL,
        pickup_datetime        DATETIME NOT NULL,          -- NYC local time, as published by TLC
        dropoff_datetime       DATETIME NOT NULL,
        pickup_location_id     SMALLINT UNSIGNED NOT NULL,
        dropoff_location_id    SMALLINT UNSIGNED NOT NULL,
        passenger_count        TINYINT UNSIGNED NULL,
        trip_distance          DECIMAL(7,2) NOT NULL,
        rate_code_id           TINYINT UNSIGNED NOT NULL,
        store_and_fwd_flag     CHAR(1) NOT NULL,
        payment_type_id        TINYINT UNSIGNED NOT NULL,
        fare_amount            DECIMAL(8,2) NOT NULL,
        extra                  DECIMAL(8,2) NOT NULL DEFAULT 0,
        mta_tax                DECIMAL(8,2) NOT NULL DEFAULT 0,
        tip_amount             DECIMAL(8,2) NOT NULL DEFAULT 0,
        tolls_amount           DECIMAL(8,2) NOT NULL DEFAULT 0,
        improvement_surcharge  DECIMAL(8,2) NOT NULL DEFAULT 0,
        congestion_surcharge   DECIMAL(8,2) NOT NULL DEFAULT 0,
        airport_fee            DECIMAL(8,2) NOT NULL DEFAULT 0,
        cbd_congestion_fee     DECIMAL(8,2) NOT NULL DEFAULT 0,
        total_amount           DECIMAL(8,2) NOT NULL,
        -- derived features
        trip_duration_min      DECIMAL(8,2) NOT NULL,
        trip_speed_mph         DECIMAL(8,2) NOT NULL,
        fare_per_mile          DECIMAL(10,2) NOT NULL,
        tip_pct                DECIMAL(8,2) NULL,
        time_of_day_bucket     ENUM('Morning','Afternoon','Evening','Night') NOT NULL,
        pickup_hour            TINYINT UNSIGNED NOT NULL,
        pickup_dow             TINYINT UNSIGNED NOT NULL,  -- 0 = Monday
        pickup_date            DATE NOT NULL,
        is_weekend             BOOLEAN NOT NULL,
        is_suspicious          BOOLEAN NOT NULL DEFAULT FALSE,
        suspicious_reasons     VARCHAR(255) NULL,
        CONSTRAINT fk_trips_vendor  FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
        CONSTRAINT fk_trips_pu_zone FOREIGN KEY (pickup_location_id) REFERENCES zones(location_id),
        CONSTRAINT fk_trips_do_zone FOREIGN KEY (dropoff_location_id) REFERENCES zones(location_id),
        CONSTRAINT fk_trips_rate    FOREIGN KEY (rate_code_id) REFERENCES rate_codes(rate_code_id),
        CONSTRAINT fk_trips_payment FOREIGN KEY (payment_type_id) REFERENCES payment_types(payment_type_id),
        CONSTRAINT chk_trips_distance CHECK (trip_distance > 0),
        CONSTRAINT chk_trips_fare     CHECK (fare_amount > 0 AND total_amount > 0),
        CONSTRAINT chk_trips_times    CHECK (dropoff_datetime > pickup_datetime),
        CONSTRAINT chk_trips_flag     CHECK (store_and_fwd_flag IN ('Y','N','U')),
        CONSTRAINT chk_trips_hour     CHECK (pickup_hour <= 23),
        CONSTRAINT chk_trips_dow      CHECK (pickup_dow <= 6)
    ) {TABLE_OPTIONS}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        run_id       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        loaded_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        rows_raw     INT UNSIGNED NULL,
        rows_clean   INT UNSIGNED NULL,
        rows_dropped INT UNSIGNED NULL,
        rows_flagged INT UNSIGNED NULL,
        report_json  LONGTEXT NULL
    ) {TABLE_OPTIONS}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS exclusion_log (
        log_id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        run_id              INT UNSIGNED NULL,
        source_row          INT UNSIGNED NULL,
        action              ENUM('dropped','flagged') NOT NULL,
        rule                VARCHAR(50) NOT NULL,
        detail              VARCHAR(255) NULL,
        pickup_datetime     DATETIME NULL,
        dropoff_datetime    DATETIME NULL,
        pickup_location_id  INT NULL,
        dropoff_location_id INT NULL,
        trip_distance       DECIMAL(12,2) NULL,
        fare_amount         DECIMAL(12,2) NULL,
        total_amount        DECIMAL(12,2) NULL,
        passenger_count     INT NULL,
        CONSTRAINT fk_exclusion_run FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
        INDEX idx_exclusion_rule (action, rule)
    ) {TABLE_OPTIONS}
    """,
]

# Secondary indexes on trips are built after the bulk load (much faster than per insert).
# (FK columns pickup/dropoff/vendor/rate/payment already get indexes from InnoDB.)
TRIP_INDEXES = {
    "idx_trips_pickup_dt": "pickup_datetime",
    "idx_trips_pickup_date": "pickup_date",
    "idx_trips_hour_dow": "pickup_hour, pickup_dow",
    "idx_trips_time_bucket": "time_of_day_bucket",
    "idx_trips_suspicious": "is_suspicious",
}

TRIP_COLUMNS = [
    "source_row", "vendor_id", "pickup_datetime", "dropoff_datetime",
    "pickup_location_id", "dropoff_location_id", "passenger_count", "trip_distance",
    "rate_code_id", "store_and_fwd_flag", "payment_type_id",
    "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "congestion_surcharge", "airport_fee", "cbd_congestion_fee",
    "total_amount", "trip_duration_min", "trip_speed_mph", "fare_per_mile", "tip_pct",
    "time_of_day_bucket", "pickup_hour", "pickup_dow", "pickup_date", "is_weekend",
    "is_suspicious", "suspicious_reasons",
]
LOG_COLUMNS = [
    "source_row", "action", "rule", "detail", "pickup_datetime", "dropoff_datetime",
    "pickup_location_id", "dropoff_location_id", "trip_distance", "fare_amount",
    "total_amount", "passenger_count",
]


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def connect(args: argparse.Namespace) -> pymysql.connections.Connection:
    """Create the database if needed, then connect to it."""
    common = dict(host=args.host, port=args.port, user=args.user, password=args.password,
                  charset="utf8mb4", autocommit=False, local_infile=False)
    server = pymysql.connect(**common)
    with server.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{args.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    server.close()
    conn = pymysql.connect(database=args.database, **common)
    log.info("Connected to %s@%s:%s/%s", args.user, args.host, args.port, args.database)
    return conn


def bulk_mode(cur, on: bool) -> None:
    """Skip per-row FK / unique checks during the load (data is validated by the pipeline)."""
    flag = 0 if on else 1
    cur.execute(f"SET SESSION foreign_key_checks = {flag}")
    cur.execute(f"SET SESSION unique_checks = {flag}")


def to_rows(df: pd.DataFrame, columns: list[str]) -> list[tuple]:
    """DataFrame -> list of tuples with Python-native values (NaN/NA -> None)."""
    out = df[columns].astype(object).where(df[columns].notna(), None)
    return list(out.itertuples(index=False, name=None))


def insert_many(cur, sql: str, rows: list[tuple]) -> None:
    # PyMySQL rewrites executemany(INSERT ... VALUES) into multi-row INSERTs
    for i in range(0, len(rows), INSERT_CHUNK):
        cur.executemany(sql, rows[i:i + INSERT_CHUNK])


def format_trip_batch(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["pickup_datetime", "dropoff_datetime"]:
        df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d %H:%M:%S")
    df["pickup_date"] = pd.to_datetime(df["pickup_date"]).dt.strftime("%Y-%m-%d")
    for col in ["is_weekend", "is_suspicious"]:
        df[col] = df[col].astype(bool).astype(int)
    df["suspicious_reasons"] = df["suspicious_reasons"].replace("", None)
    for col in ["vendor_id", "passenger_count", "rate_code_id", "payment_type_id",
                "pickup_location_id", "dropoff_location_id", "pickup_hour", "pickup_dow", "source_row"]:
        df[col] = df[col].astype("Int64")
    return df


# --------------------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------------------
def create_schema(cur, rebuild: bool) -> None:
    if rebuild:
        log.info("Dropping existing tables")
        cur.execute("SET SESSION foreign_key_checks = 0")
        for table in ALL_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute("SET SESSION foreign_key_checks = 1")
    for ddl in SCHEMA:
        cur.execute(ddl)


def insert_lookups(cur, extra_vendor_ids: set[int]) -> None:
    vendors = dict(VENDORS)
    for vid in extra_vendor_ids - set(vendors):
        vendors[vid] = f"Unknown vendor {vid}"
    cur.executemany("REPLACE INTO vendors VALUES (%s, %s)", sorted(vendors.items()))
    cur.executemany("REPLACE INTO rate_codes VALUES (%s, %s)", sorted(RATE_CODES.items()))
    cur.executemany("REPLACE INTO payment_types VALUES (%s, %s)", sorted(PAYMENT_TYPES.items()))
    log.info("Lookups: %d vendors, %d rate codes, %d payment types",
             len(vendors), len(RATE_CODES), len(PAYMENT_TYPES))


def insert_zones(cur, processed: Path) -> None:
    zones = pd.read_csv(processed / "zones_clean.csv")
    geometries: dict[str, dict] = {}
    geo_file = processed / "zone_geometries.json"
    if geo_file.exists():
        with open(geo_file, encoding="utf-8") as fh:
            geometries = json.load(fh)

    boroughs = {name: i for i, name in enumerate(sorted(zones["borough"].unique()), start=1)}
    services = {name: i for i, name in enumerate(sorted(zones["service_zone"].unique()), start=1)}
    cur.executemany("REPLACE INTO boroughs VALUES (%s, %s)", [(i, n) for n, i in boroughs.items()])
    cur.executemany("REPLACE INTO service_zones VALUES (%s, %s)", [(i, n) for n, i in services.items()])

    rows = []
    for z in zones.itertuples(index=False):
        geom = geometries.get(str(int(z.location_id)))
        lat = None if pd.isna(z.centroid_lat) or abs(z.centroid_lat) > 90 else round(float(z.centroid_lat), 6)
        lng = None if pd.isna(z.centroid_lng) or abs(z.centroid_lng) > 180 else round(float(z.centroid_lng), 6)
        rows.append((int(z.location_id), z.zone_name, boroughs[z.borough], services[z.service_zone],
                     lat, lng, json.dumps(geom) if geom else None))
    cur.executemany("REPLACE INTO zones VALUES (%s, %s, %s, %s, %s, %s, %s)", rows)
    log.info("Zones: %d zones, %d boroughs, %d service zones, %d with geometry",
             len(rows), len(boroughs), len(services), sum(1 for r in rows if r[6]))


def insert_trips(conn, cur, trips_file: Path) -> int:
    pf = pq.ParquetFile(trips_file)
    total = pf.metadata.num_rows
    log.info("Trips: inserting %s rows", f"{total:,}")

    sql = (f"INSERT INTO trips ({', '.join(TRIP_COLUMNS)}) "
           f"VALUES ({', '.join(['%s'] * len(TRIP_COLUMNS))})")
    done, t0 = 0, time.time()
    for batch in pf.iter_batches(batch_size=READ_BATCH, columns=TRIP_COLUMNS):
        df = format_trip_batch(batch.to_pandas())
        insert_many(cur, sql, to_rows(df, TRIP_COLUMNS))
        conn.commit()
        done += len(df)
        log.info("  %10s / %s  (%.0f rows/s)", f"{done:,}", f"{total:,}", done / max(time.time() - t0, 1e-6))
    return done


def insert_exclusion_log(conn, cur, processed: Path, run_id: int) -> int:
    path = processed / "exclusion_log.csv"
    if not path.exists():
        log.warning("No exclusion_log.csv found - skipping")
        return 0
    sql = (f"INSERT INTO exclusion_log (run_id, {', '.join(LOG_COLUMNS)}) "
           f"VALUES ({', '.join(['%s'] * (len(LOG_COLUMNS) + 1))})")
    n = 0
    for chunk in pd.read_csv(path, chunksize=READ_BATCH, low_memory=False):
        for col in LOG_COLUMNS:
            if col not in chunk.columns:
                chunk[col] = None
        # Raw values in the log can be anything (that's why they were excluded): keep them storable
        for col in ["pickup_datetime", "dropoff_datetime"]:
            ts = pd.to_datetime(chunk[col], errors="coerce")
            ts = ts.where((ts.dt.year >= 1000) & (ts.dt.year <= 9999))
            chunk[col] = ts.dt.strftime("%Y-%m-%d %H:%M:%S")
        for col in ["source_row", "pickup_location_id", "dropoff_location_id", "passenger_count"]:
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce").astype("Int64")
        for col in ["trip_distance", "fare_amount", "total_amount"]:
            num = pd.to_numeric(chunk[col], errors="coerce")
            chunk[col] = num.where(num.abs() < 1e10).round(2)
        rows = [(run_id, *r) for r in to_rows(chunk, LOG_COLUMNS)]
        insert_many(cur, sql, rows)
        conn.commit()
        n += len(rows)
    log.info("Exclusion log: %s entries", f"{n:,}")
    return n


def record_run(cur, processed: Path) -> int:
    report = {}
    path = processed / "cleaning_report.json"
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            report = json.load(fh)
    cur.execute(
        "INSERT INTO pipeline_runs (rows_raw, rows_clean, rows_dropped, rows_flagged, report_json) "
        "VALUES (%s, %s, %s, %s, %s)",
        (report.get("rows_raw"), report.get("rows_clean"), report.get("rows_dropped"),
         report.get("rows_flagged_suspicious"), json.dumps(report)),
    )
    return cur.lastrowid


def build_indexes(cur) -> None:
    log.info("Building indexes")
    cur.execute("SELECT index_name FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'trips'")
    existing = {r[0] for r in cur.fetchall()}
    for name, cols in TRIP_INDEXES.items():
        if name not in existing:
            cur.execute(f"CREATE INDEX {name} ON trips ({cols})")
    cur.execute("ANALYZE TABLE trips, zones, exclusion_log")
    cur.fetchall()


def verify(cur) -> None:
    """Sanity checks printed at the end of the load (FK checks were off during the load)."""
    def q(sql):
        cur.execute(sql)
        return cur.fetchone()[0]

    log.info("Verification")
    log.info("  trips:                    %s", f"{q('SELECT COUNT(*) FROM trips'):,}")
    log.info("  zones:                    %s", q("SELECT COUNT(*) FROM zones"))
    checks = {
        "orphan pickup zones": "SELECT COUNT(*) FROM trips t LEFT JOIN zones z ON t.pickup_location_id = z.location_id WHERE z.location_id IS NULL",
        "orphan dropoff zones": "SELECT COUNT(*) FROM trips t LEFT JOIN zones z ON t.dropoff_location_id = z.location_id WHERE z.location_id IS NULL",
        "orphan vendors": "SELECT COUNT(*) FROM trips t LEFT JOIN vendors v USING (vendor_id) WHERE t.vendor_id IS NOT NULL AND v.vendor_id IS NULL",
        "orphan rate codes": "SELECT COUNT(*) FROM trips t LEFT JOIN rate_codes r USING (rate_code_id) WHERE r.rate_code_id IS NULL",
        "orphan payment types": "SELECT COUNT(*) FROM trips t LEFT JOIN payment_types p USING (payment_type_id) WHERE p.payment_type_id IS NULL",
    }
    problems = 0
    for label, sql in checks.items():
        n = q(sql)
        problems += n
        log.info("  %-25s %s", label + ":", n)
    log.info("  pickup date range:        %s .. %s",
             q("SELECT MIN(pickup_date) FROM trips"), q("SELECT MAX(pickup_date) FROM trips"))
    log.info("  suspicious trips:         %s", f"{q('SELECT COUNT(*) FROM trips WHERE is_suspicious'):,}")
    if problems:
        log.error("  %d rows break foreign-key relationships - check the pipeline output", problems)


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert cleaned NYC taxi data into MySQL.")
    parser.add_argument("--host", default=os.environ.get("DB_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DB_PORT", 3306)))
    parser.add_argument("--user", default=os.environ.get("DB_USER", "root"))
    parser.add_argument("--password", default=os.environ.get("DB_PASSWORD", ""))
    parser.add_argument("--database", default=os.environ.get("DB_NAME", "nyc_taxi"))
    parser.add_argument("--processed", type=Path, default=DEFAULT_PROCESSED_DIR,
                        help="directory with pipeline outputs")
    parser.add_argument("--append", action="store_true",
                        help="keep existing data and append (default: rebuild from scratch)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    trips_file = args.processed / "trips_clean.parquet"
    if not trips_file.exists():
        parser.error(f"{trips_file} not found - run pipeline/data_pipeline.py first")

    t0 = time.time()
    conn = connect(args)
    try:
        with conn.cursor() as cur:
            create_schema(cur, rebuild=not args.append)
            bulk_mode(cur, True)

            vendor_ids = pq.read_table(trips_file, columns=["vendor_id"]).column(0).drop_null().unique().to_pylist()
            insert_lookups(cur, {int(v) for v in vendor_ids})
            insert_zones(cur, args.processed)
            run_id = record_run(cur, args.processed)
            conn.commit()

            insert_trips(conn, cur, trips_file)
            insert_exclusion_log(conn, cur, args.processed, run_id)

            bulk_mode(cur, False)
            build_indexes(cur)
            conn.commit()
            verify(cur)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log.info("Loaded into MySQL database '%s' in %.1fs", args.database, time.time() - t0)


if __name__ == "__main__":
    main()