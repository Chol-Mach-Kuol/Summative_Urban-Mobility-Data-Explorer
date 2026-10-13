import json
import math
import struct
from pathlib import Path


ROOT=Path(__file__).resolve().parent.parent
ZONES_DIR = ROOT / "data" / "raw" / "taxi_zones"
OUT_PATH = ROOT / "data" / "processed" / "taxi_zones.geojson"

COORD_DECIMALS = 5
US_FOOT=0.3048006096012192
A=6378137.0
INV_F=298.257222101
F_ = 1 / INV_F
E = math.sqrt(2 * F_ - F_ * F_) 

LAT1=math.radians(40.66666666666666)
LAT2=math.radians(41.03333333333333)
LAT0=math.radians(40.16666666666666)
LON0=math.radians(-74.0)
FALSE_EASTING=984250.0 * US_FOOT
FALSE_NORTHING=0.0

def _m(phi):
    return math.cos(phi)/math.sqrt(1 - (E * math.sin(phi)) ** 2)

def _t(phi):
    es = E * math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - es) / (1 + es)) ** (E / 2)

_M1,_M2=_m(LAT1),_m(LAT2)
_T0, _T1, _T2 = _t(LAT0), _t(LAT1), _t(LAT2)
N=(math.log(_M1) - math.log(_M2)) / (math.log(_T1) - math.log(_T2))
F_CONST= _M1 / (N * _T1 ** N)
RHO0 = A * F_CONST * _T0 ** N

def state_plane_to_lonlat(x_ft, y_ft):
    x = x_ft * US_FOOT - FALSE_EASTING
    y = y_ft * US_FOOT - FALSE_NORTHING
    rho = math.copysign(math.sqrt(x * x + (RHO0 - y) ** 2), N)
    theta = math.atan2(x, RHO0 - y)
    t = (rho / (A * F_CONST)) ** (1 / N)
    
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(15):
        es = E * math.sin(phi)
        new_phi = math.pi / 2 - 2 * math.atan(t * ((1 - es) / (1 + es)) ** (E / 2))
        if abs(new_phi - phi) < 1e-12:
            phi = new_phi
            break
        phi=new_phi
    lon=theta/N+LON0
    return round(math.degrees(lon), COORD_DECIMALS), round(math.degrees(phi), COORD_DECIMALS)


def read_dbf(path):
    data=path.read_bytes()
    n_records = struct.unpack("<I", data[4:8])[0]
    header_len, record_len = struct.unpack("<HH", data[8:12])
    
    fields=[]
    pos=32
    
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\x00")[0].decode("ascii")
        ftype=chr(data[pos + 11])
        length=data[pos+16]
        decimals=data[pos+17]
        fields.append((name, ftype, length, decimals))
        pos+=32
        
    records=[]
    pos=header_len
    for _ in range(n_records):
        raw = data[pos:pos + record_len]
        pos+=record_len
        if raw[0:1] == b"*":       # deleted record flag
            continue
        offset = 1
        rec = {}
        for name, ftype, length, decimals in fields:
            value = raw[offset:offset + length].decode("latin-1").strip()
            offset += length
            if ftype in ("N", "F"):
                value = (float(value) if decimals else int(float(value))) if value else None
            rec[name] = value
        records.append(rec)
    return records


def _ring_area(ring):
    s=0.0
    for i in range(len(ring)-1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        s += x1 * y2 - x2 * y1
    return s/2


def read_shp(path):
    data = path.read_bytes()
    shape_type = struct.unpack("<i", data[32:36])[0]
    if shape_type != 5:
        raise ValueError(f"Expected polygon shapefile (type 5), got type {shape_type}")

    shapes = []
    pos = 100  # file header is always 100 bytes
    while pos < len(data):
        _rec_num, content_words = struct.unpack(">ii", data[pos:pos + 8])
        content = data[pos + 8:pos + 8 + content_words * 2]
        pos += 8 + content_words * 2

        rec_type = struct.unpack("<i", content[0:4])[0]
        if rec_type == 0:  # null shape
            shapes.append([])
            continue
        num_parts, num_points = struct.unpack("<ii", content[36:44])
        parts = list(struct.unpack(f"<{num_parts}i", content[44:44 + 4 * num_parts]))
        pts_start = 44 + 4 * num_parts
        flat = struct.unpack(f"<{2 * num_points}d", content[pts_start:pts_start + 16 * num_points])
        points = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]

        parts.append(num_points)
        rings = [points[parts[i]:parts[i + 1]] for i in range(num_parts)]
        shapes.append(rings)
    return shapes


def rings_to_geometry(rings):
    polygons=[]
    for ring in rings:
        projected=[]
        for x,y in ring:
            pt = state_plane_to_lonlat(x, y)
            if not projected or projected[-1] != pt:
                projected.append(pt)
        if len(projected) < 4:
            continue
        if projected[0] != projected[-1]:
            projected.append(projected[0])
        is_outer = _ring_area(ring) < 0
        projected.reverse()
        if is_outer or not polygons:
            polygons.append([projected])
        else:
            polygons[-1].append(projected)
            
    if len(polygons)==1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}
        

def find_shapefile():
    for path in (ZONES_DIR / "taxi_zones.shp", ZONES_DIR / "taxi_zones" / "taxi_zones.shp"):
        if path.exists() and path.with_suffix(".dbf").exists():
            return path
    raise SystemExit(f"taxi_zones.shp (with its .dbf) not found in {ZONES_DIR.relative_to(ROOT)}/ "
                     "Extract taxi_zones.zip there (see README section 2).")       
        

def main():
    shp_path = find_shapefile()
    records = read_dbf(shp_path.with_suffix(".dbf"))
    shapes = read_shp(shp_path)
    if len(records) != len(shapes):
        raise ValueError(f"{len(records)} attribute rows but {len(shapes)} shapes")

    merged = {}
    for rec, rings in zip(records, shapes):
        if not rings:
            continue
        loc_id = rec["LocationID"]
        geom = rings_to_geometry(rings)
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        if loc_id not in merged:
            merged[loc_id] = {
                "properties": {"location_id": loc_id, "zone": rec["zone"], "borough": rec["borough"]},
                "polygons": [],
                "pieces": 0,
            }
        merged[loc_id]["polygons"].extend(polys)
        merged[loc_id]["pieces"] += 1

    features = []
    for loc_id in sorted(merged):
        item = merged[loc_id]
        if item["pieces"] > 1:
            print(f"  note: LocationID {loc_id} had {item['pieces']} separate shapes -> merged")
        polys = item["polygons"]
        geometry = ({"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1
                    else {"type": "MultiPolygon", "coordinates": polys})
        features.append({"type": "Feature", "properties": item["properties"], "geometry": geometry})

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                   separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(features)} zones ({len(records)} raw shapes) to "
          f"{OUT_PATH.relative_to(ROOT)} ({OUT_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
    
