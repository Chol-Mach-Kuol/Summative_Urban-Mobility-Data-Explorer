import random
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python make_sample.py path/to/yellow_tripdata.csv [fraction]")
    sys.exit(1)

src=Path(sys.argv[1])
fraction=float(sys.argv[2]) if len(sys.argv) > 2 else 0.05
dst=src.with_name("yellow_tripdata_sample.csv")

random.seed(42)
total=kept=0

with open(src, "r", encoding="utf-8", newline="") as fin, \
     open(dst, "w", encoding="utf-8", newline="") as fout:
    fout.write(fin.readline()) 
    for line in fin:
        total+=1
        if random.random() < fraction:
            fout.write(line)
            kept+=1
        if total % 500_000==0:
           print(f"  read {total:,} rows...") 

print(f"Done. Read {total:,} rides, kept {kept:,} ({fraction:.0%}).")
print(f"Sample saved to: {dst}  ({dst.stat().st_size / 1e6:.1f} MB)")