# Algorithm Notes — Chol Mach Kuol

## 1. top_k(items, k, key)

**What it does:**
Returns the k largest items from a list ranked by a key function.
Used in app.py to find the top routes and top destinations without sorting everything.

**Approach:**
Min-heap of size k. For each item, if it scores higher than the smallest item in the heap, replace it.

**Time complexity:**
- O(n log k) — much faster than O(n log n) full sort when k is small (e.g. top 10 from 63,000 routes)

**Why this approach:**
Sorting all routes just to show the top 10 wastes time. A min-heap only tracks k items at once.

---

## 2. count_by(items)

**What it does:**
Counts how many times each value appears in a list. Returns a dict of {value: count}.
Used in app.py to count how many trips went to each dropoff zone.

**Approach:**
Single pass over the list, incrementing a dict counter for each value.

**Time complexity:**
- O(n) — one pass, no sorting

**Why this approach:**
Simplest and fastest way to aggregate counts. Python's dict lookup is O(1) average.

---

## 3. quickselect_median(values)

**What it does:**
Finds the median fare for a zone without sorting the full list.
Used in app.py for the zone detail panel — median is more robust than mean for skewed fares.

**Approach:**
Quickselect (partition-based selection). Picks a pivot, partitions the list, and recurses only on the half containing the target index.

**Time complexity:**
- O(n) average — avoids the O(n log n) cost of a full sort

**Why this approach:**
Fare distributions are skewed (outliers like $200 airport rides). Median gives a fairer "typical fare" than the mean. Quickselect gets it in O(n) instead of sorting first.
