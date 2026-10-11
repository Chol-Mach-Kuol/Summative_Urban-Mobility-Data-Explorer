# NYC Urban Mobility Data Explorer

> 🎥 **Video walkthrough:** _[Add link here before submission]_

A full-stack dashboard for exploring NYC Yellow Taxi trip patterns — built with Flask, SQLite, and vanilla JS.

---

## Project Structure

```
├── backend/
│   ├── app.py                  # Flask entry point
│   └── routes/
│       ├── trips.py            # GET /api/trips/
│       ├── zones.py            # GET /api/zones/, /api/zones/geojson
│       └── insights.py         # GET /api/insights/*
├── database/
│   ├── schema.sql              # Normalized schema + indexes
│   └── db.py                   # SQLite connection helper
├── pipeline/
│   ├── clean.py                # Data cleaning + feature engineering
│   └── load.py                 # Insert cleaned data into DB
├── frontend/
│   ├── index.html              # Dashboard shell
│   ├── css/style.css
│   └── js/
│       ├── api.js              # Fetch helpers
│       ├── charts.js           # Chart.js + Leaflet renders
│       ├── table.js            # Paginated trip table + KPIs
│       └── main.js             # Filter wiring + bootstrap
├── data/
│   ├── raw/                    # Place source files here (git-ignored)
│   └── processed/              # Output of pipeline (git-ignored)
├── docs/screenshots/
├── codevibe-reports/           # One .report.json per team member
├── requirements.txt
└── README.md
```

---

## Setup

### 1. Clone & install Python dependencies

```bash
git clone <your-team-repository-url>
cd Summative_Urban-Mobility-Data-Explorer
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add raw data files

Place the following files in `data/raw/`:

| File | Source |
|------|--------|
| `yellow_tripdata_*.parquet` | [TLC Trip Records](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) |
| `taxi_zone_lookup.csv` | Provided in assignment |
| `taxi_zones.geojson` | Provided in assignment (rename if needed) |

### 3. Run the data pipeline

```bash
python pipeline/clean.py   # cleans + engineers features → data/processed/
python pipeline/load.py    # loads processed data into database/mobility.db
```

### 4. Start the backend

```bash
python backend/app.py
# API available at http://localhost:5000
```

### 5. Open the frontend

Open `frontend/index.html` directly in your browser, **or** serve it with:

```bash
python -m http.server 8080 --directory frontend
# Dashboard at http://localhost:8080
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/trips/` | Paginated trips with filters |
| GET | `/api/zones/` | All taxi zones |
| GET | `/api/zones/geojson` | Zone GeoJSON boundaries |
| GET | `/api/insights/hourly-demand` | Trips per hour of day |
| GET | `/api/insights/top-routes` | Top borough-to-borough routes |
| GET | `/api/insights/fare-vs-distance` | Sampled fare vs distance |
| GET | `/api/insights/borough-summary` | Avg speed/fare/duration by borough |

### Trip filter params

`date_from`, `date_to`, `pu_location_id`, `do_location_id`, `min_distance`, `max_distance`, `min_fare`, `max_fare`, `payment_type`, `limit` (max 500), `offset`

---

## Derived Features

| Feature | Formula | Insight |
|---------|---------|---------|
| `trip_duration_min` | `(dropoff − pickup) / 60s` | Proxy for congestion |
| `speed_mph` | `distance / (duration / 60)` | Flags anomalous trips |
| `fare_per_mile` | `fare_amount / trip_distance` | Economic efficiency |

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
