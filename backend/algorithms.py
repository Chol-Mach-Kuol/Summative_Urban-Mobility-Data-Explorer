"""
algorithms.py  —  Chol Mach Kuol
Hand-written algorithms used by app.py for ranking and statistics.
"""


def top_k(items, k, key):
    """
    Return the k largest items by key using a hand-written min-heap.
    Time complexity: O(n log k)  —  faster than sorting all n items when k << n.
    Space complexity: O(k)  —  heap never grows beyond k entries.
    """
    heap = []   # list of (val, tiebreak, item), maintained as a min-heap

    def _sift_up(h, i):
        while i > 0:
            parent = (i - 1) // 2
            if h[i][0] < h[parent][0]:
                h[i], h[parent] = h[parent], h[i]
                i = parent
            else:
                break

    def _sift_down(h, i):
        n = len(h)
        while True:
            smallest, left, right = i, 2 * i + 1, 2 * i + 2
            if left < n and h[left][0] < h[smallest][0]:
                smallest = left
            if right < n and h[right][0] < h[smallest][0]:
                smallest = right
            if smallest == i:
                break
            h[i], h[smallest] = h[smallest], h[i]
            i = smallest

    for tiebreak, item in enumerate(items):
        val = key(item)
        if len(heap) < k:
            heap.append((val, tiebreak, item))
            _sift_up(heap, len(heap) - 1)
        elif val > heap[0][0]:
            heap[0] = (val, tiebreak, item)
            _sift_down(heap, 0)

    # sort descending by val to return ranked results
    result = []
    while heap:
        # pop min, swap root with last element then sift down
        heap[0], heap[-1] = heap[-1], heap[0]
        result.append(heap.pop()[2])
        if heap:
            _sift_down(heap, 0)
    result.reverse()
    return result


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
