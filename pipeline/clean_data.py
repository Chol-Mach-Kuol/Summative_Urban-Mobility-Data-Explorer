import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from trips_io import input_path, read_trips

ROOT=Path(__file__).resolve().parent.parent
LOOKUP_CSV=ROOT / 'data' / 'raw' / 'taxi_zone_lookup.csv'
OUT_DIR=ROOT / 'data' / 'processed'

MONTH_START=pd.Timestamp('2019-01-01')
MONTH_END=pd.Timestamp('2019-02-01')
MAX_DURATION_MIN=6*60
MAX_DISTANCE_MI=100
MAX_FARE=500
MAX_SPEED_MPH=80
AIRPORT_ZONES={1,132,138}
UNKNOWN_ZONES={264,265}
MIN_DISTANCE_FOR_RATIO=0.25
NYC_BASE_FARE=2.50

VALID_RATECODES={1,2,3,4,5,6}
VALID_PAYMENT_TYPES={1,2,3,4,5,6}
MONEY_COLS=["fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
              "improvement_surcharge", "congestion_surcharge", "total_amount"]

def load_raw(path):
    print(f"Loading {path.name} ...")
    df=read_trips(path)
    df.insert(0,'source_row',np.arange(1,len(df)+1))
    print(f"{len(df):,} rides loaded")
    return df

def apply_exclusion_rules(df):
    duration_min=(df["tpep_dropoff_datetime"] - df["tpep_pickup_datetime"]).dt.total_seconds() / 60
    hours=duration_min/60
    speed=df["trip_distance"] / hours.where(hours > 0)
    negative_component=(df[["extra", "mta_tax", "tip_amount", "tolls_amount",
                              "improvement_surcharge", "total_amount"]] < 0).any(axis=1)
    duplicate=df.drop(columns='source_row').duplicated(keep='first')
    
    rules= [
        ("duplicate_record", duplicate),
        ("pickup_outside_jan_2019",
         (df["tpep_pickup_datetime"] < MONTH_START) | (df["tpep_pickup_datetime"] >= MONTH_END)),
        ("dropoff_not_after_pickup", duration_min <= 0),
        (f"duration_over_{MAX_DURATION_MIN // 60}h", duration_min > MAX_DURATION_MIN),
        ("zero_distance", df["trip_distance"] <= 0),
        (f"distance_over_{MAX_DISTANCE_MI}mi", df["trip_distance"] > MAX_DISTANCE_MI),
        ("fare_zero_or_negative", df["fare_amount"] <= 0),
        # Below the $2.50 flag-drop no metered ride is possible. 98% of these are
        # negotiated / no-charge placeholders, e.g. $0.01 for a 33-mile ride.
        ("fare_below_base_fare", df["fare_amount"] < NYC_BASE_FARE),
        (f"fare_over_{MAX_FARE}", df["fare_amount"] > MAX_FARE),
        ("negative_charge_component", negative_component),
        # Fare, tax and tip present but a $0 total: the total was never recorded
        # (13 rides, all vendor 5 / payment type 0, in the TLC parquet release).
        ("total_zero", df["total_amount"] == 0),
        (f"speed_over_{MAX_SPEED_MPH}mph", speed > MAX_SPEED_MPH),
    ]
    
    reason=pd.Series(pd.NA, index=df.index,dtype='string')
    for name,mask in rules:
        reason=reason.mask(reason.isna() & mask.fillna(False),name)
    excluded=df[reason.notna()].copy()
    excluded=insert(1,'exclusion_reason',reason[reason.notna()])
    kept=df[reason.isna()].copy()
    counts = {name: int((reason == name).sum()) for name, _ in rules}
    return kept,exluded,counts

def repair_and_normalize(df,lookup):
    notes=pd.Series('',index=df.index,dtype='string')
    def note(mask,text):
        nonlocal notes
        notes=notes.mask(mask,notes.where(notes=='',notes+';') + text)
    df['congestion_surcharge']=df['congestion_surcharge'].fillna(0.0)
    zero_pax=df['passenger_count']==0
    note(zero_pax,'passenger_count_0_set_unknown')
    df['passenger_count']=df['passenger_copunt'].astype("Int64").mask(zero_pax)
    no_meta=df['RatecodeID'].isna()
    note(no_meta,'trip_metadata_missing')
    
    bad_rate=df['RatecodeID'].notna() & ~df["RatecodeID"].isin(VALID_RATECODES)
    note((bad_rate, "invalid_ratecode_set_unknown"))
    df["RatecodeID"] = df["RatecodeID"].astype("Int64").mask(bad_rate)
    
    bad_payment=~df['payment_type'].isin(VALID_PAYMENT_TYPES)
    note(bad_payment,"invalid_payment_type_set_unknown")
    df['payment_type']=df['payment_type'].mask(bad_payment, 5).astype("int64")
    note(~df["VendorID"].isin([1, 2]), "undocumented_vendor_id")
    
    parts=df[MONEY_COLS[:-1]].sum(axis=1)
    note((parts-df['total_amount']).abs() > 0.01,"total_not_equal_sum_of_parts")
    
    note(df["PULocationID"].isin(UNKNOWN_ZONES), "pickup_zone_unknown")
    note(df["DOLocationID"].isin(UNKNOWN_ZONES), "dropoff_zone_unknown")
    
    valid_zone_ids=set(lookup['LocationID'])
    bad_zone=~df["PULocationID"].isin(valid_zone_ids) | ~df["DOLocationID"].isin(valid_zone_ids)
    if bad_zone_any():
        raise ValueError(f"{int(bad_zone.sum())} rides reference zones missing from the lookup")
    
    for col in MONEY_COLS:
        df[col]=df[col].round(2)
    
    df["trip_distance"] = df["trip_distance"].round(2)
    
    
    df["store_and_fwd_flag"] = df["store_and_fwd_flag"].eq("Y").fillna(False).astype("int8")
    df = df.rename(columns={
        "VendorID": "vendor_id",
        "tpep_pickup_datetime": "pickup_datetime",
        "tpep_dropoff_datetime": "dropoff_datetime",
        "RatecodeID": "rate_code_id",
        "PULocationID": "pickup_zone_id",
        "DOLocationID": "dropoff_zone_id",
        "payment_type": "payment_type_id",
    })
    
    uspicious = df.loc[notes != "", ["source_row", "pickup_datetime", "vendor_id",
                                      "pickup_zone_id", "dropoff_zone_id",
                                      "fare_amount", "total_amount"]].copy()
    suspicious.insert(1, "issues", notes[notes != ""])
    issue_counts = (notes[notes != ""].str.split(";").explode().value_counts().to_dict())
    return df,suspicious, {k:int(v) for k,v in issue_counts.items()}
    
    
def add_features(df):
    duration_min=(df["dropoff_datetime"] - df["pickup_datetime"]).dt.total_seconds() / 60
    df['trip_duration_min']=duration_min.round(2)
    df['avg_speed_mph']=(df['trip_distance']/(duration_min/60)).round(2)
    
    long_enough = df["trip_distance"] >= MIN_DISTANCE_FOR_RATIO
    df["fare_per_mile"] = (df["fare_amount"] / df["trip_distance"]).round(2).where(long_enough)
    
    is_card=df['payment_type_id']==1
    real_fare=df['fare_amount'] >= NYC_BASE_FARE
    df["tip_pct"] = (df["tip_amount"] / df["fare_amount"] * 100).round(2).where(is_card & real_fare)
    
    df['pickup_hour']=df["pickup_datetime"].dt.hour.astype("int8")
    df['pickup_dow']=df["pickup_datetime"].dt.dayofweek.astype("int8")
    df['is_weekend']=(df['pickup_dow'] >= 5).astype('int8')
    df["time_of_day"] = pd.cut(
        df["pickup_hour"], bins=[-1, 5, 9, 15, 19, 23],
        labels=["night", "morning_rush", "midday", "evening_rush", "evening"],
    ).astype("string")
    
    df["is_airport_trip"] = (df["pickup_zone_id"].isin(AIRPORT_ZONES)
                             | df["dropoff_zone_id"].isin(AIRPORT_ZONES)).astype("int8")
    
    return df

def main():
    raw_path = input_path("Clean, normalize and enrich the raw yellow taxi trips.")
    start = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw = load_raw(raw_path)
    lookup = pd.read_csv(LOOKUP_CSV)
    total = len(raw)

    print("Applying exclusion rules ...")
    kept, excluded, exclusion_counts = apply_exclusion_rules(raw)
    del raw
    for name, count in exclusion_counts.items():
        print(f"  {name:<30}{count:>9,}")
    print(f"  {'TOTAL EXCLUDED':<30}{len(excluded):>9,}  ({len(excluded) / total:.2%})")

    print("Repairing and normalizing kept rides ...")
    kept, suspicious, issue_counts = repair_and_normalize(kept, lookup)
    for name, count in issue_counts.items():
        print(f"  {name:<30}{count:>9,}")

    print("Adding derived features ...")
    kept = add_features(kept)

    print("Saving outputs ...")
    ts_format = "%Y-%m-%d %H:%M:%S"
    kept.to_csv(OUT_DIR / "trips_clean.csv", index=False, date_format=ts_format)
    excluded.to_csv(OUT_DIR / "excluded_records.csv", index=False, date_format=ts_format)
    suspicious.to_csv(OUT_DIR / "suspicious_records.csv", index=False, date_format=ts_format)

    summary = {
        "source_file": raw_path.name,
        "raw_rows": total,
        "clean_rows": len(kept),
        "excluded_rows": len(excluded),
        "excluded_pct": round(len(excluded) / total * 100, 3),
        "exclusion_reasons": exclusion_counts,
        "repaired_or_flagged_rows": len(suspicious),
        "repair_and_flag_reasons": issue_counts,
        "thresholds": {
            "max_duration_min": MAX_DURATION_MIN, "max_distance_mi": MAX_DISTANCE_MI,
            "max_fare": MAX_FARE, "max_speed_mph": MAX_SPEED_MPH,
        },
    }
    (OUT_DIR / "cleaning_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nDone in {time.time() - start:.0f}s: {len(kept):,} clean rides "
          f"({len(excluded):,} excluded, {len(suspicious):,} repaired/flagged).")

if __name__ == "__main__":
    main()