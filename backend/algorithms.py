"""
algorithms.py  —  Chol Mach Kuol
Hand-written algorithms used by app.py for ranking and statistics.
"""


def top_k(items, k, key):
    """
    Return the k largest items by key using a min-heap.
    Time complexity: O(n log k)  —  faster than sorting all n items when k << n.
    """
    import heapq
    heap = []
    for i, item in enumerate(items):
        val = key(item)
        if len(heap) < k:
            heapq.heappush(heap, (val, i, item))
        elif val > heap[0][0]:
            heapq.heapreplace(heap, (val, i, item))
    return [item for _, _, item in sorted(heap, key=lambda x: x[0], reverse=True)]


def count_by(items):
    """
    Count occurrences of each value in items into a dict.
    Time complexity: O(n)
    """
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def quickselect_median(values):
    """
    Find the median using quickselect — O(n) average, no full sort needed.
    More robust than the mean for skewed fare distributions.
    """
    if not values:
        return None
    lst = list(values)
    n = len(lst)
    if n % 2 == 1:
        return _quickselect(lst, n // 2)
    return round((_quickselect(lst, n // 2 - 1) + _quickselect(lst, n // 2)) / 2, 2)


def _quickselect(lst, k):
    """Return the k-th smallest element in lst (in-place partition, O(n) average)."""
    lo, hi = 0, len(lst) - 1
    while lo < hi:
        pivot = lst[(lo + hi) // 2]
        i, j = lo, hi
        while i <= j:
            while lst[i] < pivot:
                i += 1
            while lst[j] > pivot:
                j -= 1
            if i <= j:
                lst[i], lst[j] = lst[j], lst[i]
                i += 1
                j -= 1
        if k <= j:
            hi = j
        elif k >= i:
            lo = i
        else:
            break
    return lst[k]
