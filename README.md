# NYC Urban Mobility Data Explorer

> 🎥 **Video walkthrough:** _[Add link here before submission]_

A full-stack dashboard for exploring NYC Yellow Taxi trip patterns — built with Flask, SQLite, and vanilla JS.

---

## Project Structure

```
├── backend/
│   ├── app.py                  # Flask entry point + all API endpoints
│   ├── algorithms.py           # Hand-written top_k, count_by, quickselect_median
│   └── db.py                   # SQLite connection, filter parsing, WHERE builder
├── database/
│   ├── schema.sql              # Star schema + CHECK constraints
│   ├── indexes.sql             # Performance indexes
│   └── load_database.py        # Bulk insert + summary table builder
├── pipeline/
│   ├── clean_data.py           # Data cleaning + feature engineering
│   ├── trips_io.py             # CSV/Parquet read helpers
│   ├── convert_zones.py        # Shapefile → GeoJSON conversion
│   ├── make_sample.py          # Creates a smaller sample dataset
│   └── profile_data.py         # Data profiling / EDA
├── frontend/
│   ├── index.html              # Dashboard shell
│   ├── css/style.css
│   └── js/
│       ├── api.js              # Fetch helpers
│       ├── charts.js           # Chart.js renders
│       ├── map.js              # Leaflet choropleth map
│       ├── main.js             # Filter wiring + bootstrap
│       └── theme.js            # Dark/light mode toggle
├── data/
│   ├── raw/                    # Place source files here (git-ignored)
│   └── processed/              # Output of pipeline (git-ignored)
├── docs/
│   ├── screenshots/            # Architecture diagram + insight screenshots
│   └── NYC_Urban_Mobility_Documentation_Report.pdf
├── codevibe-reports/           # One .report.json per team member
├── requirements.txt
└── README.md
```

---

## Setup

### 1. Clone & install Python dependencies

```bash
git clone <your-team-repository-url>
cd Summative_Urban-Mobility-Data-Explorer-1
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add raw data files

Place the following files in `data/raw/`:

| File | Source |
|------|--------|
| `yellow_tripdata_2019-01.csv` | [TLC Trip Records](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) |
| `taxi_zone_lookup.csv` | Provided in assignment |
| `taxi_zones.shp` (+ sidecar files) | Provided in assignment |

### 3. Run the data pipeline

```bash
python3 pipeline/clean_data.py   # cleans + engineers features → data/processed/
python3 database/load_database.py  # loads processed data into data/mobility.db
```

### 4. Start the backend

```bash
python3 backend/app.py
# API + dashboard available at http://127.0.0.1:5000
```

The backend also serves the frontend, so no separate step is needed. Open `http://127.0.0.1:5000` in your browser.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | DB status + total trip count |
| GET | `/api/meta` | Date range, boroughs, zones, payment types |
| GET | `/api/summary` | KPI headline numbers for current filters |
| GET | `/api/by-hour` | Trips and speed per hour of day (0–23) |
| GET | `/api/by-day` | Daily totals (time series) |
| GET | `/api/heatmap` | Weekday × hour grid (demand + speed) |
| GET | `/api/zone-stats` | Per-zone pickup stats (colours the map) |
| GET | `/api/zones/geojson` | Zone GeoJSON boundaries |
| GET | `/api/top-routes` | Top K pickup → dropoff zone pairs |
| GET | `/api/zones/<zone_id>` | Detail view for one zone |
| GET | `/api/trips` | Sortable, filterable, paginated trip list |
| GET | `/api/data-quality` | Cleaning summary + exclusion breakdown |

### Filter params (accepted by most endpoints)

`start_date`, `end_date` (YYYY-MM-DD), `borough_id`, `zone_id`, `dow` (0=Mon–6=Sun), `hour_min`, `hour_max`, `min_distance`, `max_distance`, `min_fare`, `max_fare`, `payment_type_id`, `airport_only`

---

## Derived Features

| Feature | Formula | Insight |
|---------|---------|---------|
| `trip_duration_min` | `(dropoff − pickup) / 60` | Proxy for congestion |
| `avg_speed_mph` | `distance / (duration / 60)` | Flags anomalous trips |
| `fare_per_mile` | `fare_amount / trip_distance` | Economic efficiency |
| `tip_pct` | `tip_amount / fare_amount × 100` | Tipping behaviour |

---

## Dataset

| Metric | Value |
|--------|-------|
| Raw rows | 7,667,792 |
| Clean rows | 7,578,890 |
| Excluded rows | 88,902 (1.16%) |
| Database size | 2.6 GB |
| Coverage | January 2019, NYC Yellow Taxi |

---

## Team

| Name | Role | GitHub |
|------|------|--------|
| _Member 1_ | Backend / Pipeline | @username |
| _Member 2_ | Database / Schema | @username |
| _Member 3_ | Frontend / Charts | @username |
| _Member 4_ | DSA / Insights | @username |

---

## CodeVibe Reports

Each team member's `*.report.json` is committed to `codevibe-reports/`.
