import sqlite3


def get_top_routes(conn, limit=10):
    """
    Aggregate trips by pickup/droppoff borough pair and rank by trip count.
    Time complexity: O(n) scan + O(k log k) sort where k = unique borough pairs (max 25).
    """
    sql = """
        SELECT pu_borough, do_borough,
               COUNT(*)                     AS trip_count,
               ROUND(AVG(fare_amount), 2)   AS avg_fare,
               ROUND(AVG(trip_distance), 2) AS avg_distance,
        FROM trips
        GROUP BY pu_borough, do_borough
        ORDER BY trip_count DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(r) for r in rows]

def get_zone_details(conn, zone_id):
    """
    Returns aggregated trip stats for a single pickup zone.
    Time complexity: O(n) where n = trips originating from that zone.
    """
    sql = """
        SELECT z.zone_id, z.zone_name, z.borough,
               COUNT(t.trip_id)             AS total_trips,
               ROUND(AVG(t.fare_amount), 2) AS avg_fare,
               ROUND(AVG(t.speed_mph), 2)   AS avg_speed
        FROM zones z
        LEFT JOIN trips t ON t.pu_location_id = z.zone_id
        WHERE z.zone_id = ?
        GROUP BY z.zone_id
    """
    row = conn.execute(sql, (zone_id,)).fetchone()
    return dict(row) if row else {}


if __name__ == "__main__":
    conn = sqlite3.connect("../database/mobility.db")
    conn.row_factory = sqlite3.Row
    print("Top routes:", get_top_routes(conn, limit=5))
    print("Zone details:", get_zone_details(conn, zone_id=1))
    conn.close()
