# Pattern B intensive smoke-test matrix - RESULTS

**Date**: 2026-05-26
**Total dispatches**: 15 (3 engines x 5 categories)
**Success rate**: 11/15 (73%)
**Elapsed**: 191s wall-clock
**Total cost**: $0.1823

## Per-engine summary

| Engine | Categories OK | Total tokens out | Total cost | Avg latency |
|---|---|---|---|---|
| `kimi-via-claude` | 4/5 | 790 | $0.0497 | 27.8s |
| `mimo-via-claude` | 4/5 | 221 | $0.0613 | 26.1s |
| `deepseek-via-claude` | 3/5 | 872 | $0.0714 | 58.7s |

## Full matrix

| Engine | Category | OK | Latency | In | Out | Cost | Output excerpt |
|---|---|---|---|---|---|---|---|
| `kimi-via-claude` | trivial | ok | 6.3s | 784 | 37 | $0.0055 | OK |
| `kimi-via-claude` | code | ok | 10.4s | 804 | 108 | $0.0075 | def is_palindrome(s):     return s == s[::-1] |
| `kimi-via-claude` | reasoning | ok | 8.9s | 791 | 100 | $0.0072 | Mergesort is O(n log n) because it recursively splits the array into halves, creating log n levels of recursion, and the |
| `kimi-via-claude` | long_context | ok | 23.5s | 1463 | 545 | $0.0294 | The Fenwick tree array is initialized with length `n` instead of `n + 1`, so the 1-based update loop writes past the end |
| `kimi-via-claude` | multimodal_probe | FAIL | 90.0s | 0 | 0 | $0.0000 |  |
| `mimo-via-claude` | trivial | ok | 7.5s | 1816 | 19 | $0.0128 | OK |
| `mimo-via-claude` | code | ok | 8.1s | 1834 | 25 | $0.0120 | ```python def is_palindrome(s):     return s == s[::-1] ``` |
| `mimo-via-claude` | reasoning | ok | 12.0s | 1821 | 63 | $0.0129 | Merge sort is O(n log n) because it recursively divides the array in half (producing log n levels of recursion) and perf |
| `mimo-via-claude` | long_context | ok | 12.4s | 2663 | 114 | $0.0236 | The Fenwick tree uses 1-based indexing, but the tree is allocated with only `n` elements instead of `n + 1`, causing an  |
| `mimo-via-claude` | multimodal_probe | FAIL | 90.2s | 0 | 0 | $0.0000 |  |
| `deepseek-via-claude` | trivial | ok | 34.6s | 1629 | 24 | $0.0150 | OK |
| `deepseek-via-claude` | code | FAIL | 100.1s | 0 | 0 | $0.0000 |  |
| `deepseek-via-claude` | reasoning | ok | 16.1s | 1637 | 66 | $0.0133 | Merge sort recursively divides the array in half (log n levels) and at each level performs a linear merge of all element |
| `deepseek-via-claude` | long_context | ok | 48.7s | 2699 | 782 | $0.0431 | The Fenwick tree array is allocated with size `n` (10) instead of `n + 1` (11), so the update for index `n` is silently  |
| `deepseek-via-claude` | multimodal_probe | FAIL | 94.2s | 0 | 0 | $0.0000 |  |

## Failures (full error text)

### kimi-via-claude / multimodal_probe

```
subprocess timeout after 90.0s
```

### mimo-via-claude / multimodal_probe

```
subprocess timeout after 90.0s
```

### deepseek-via-claude / code

```
subprocess timeout after 90.0s
```

### deepseek-via-claude / multimodal_probe

```
subprocess timeout after 90.0s
```


## Per-category outputs (compare engine answers)

### trivial

**kimi-via-claude** (6.3s, $0.0055):

```
OK
```

**mimo-via-claude** (7.5s, $0.0128):

```
OK
```

**deepseek-via-claude** (34.6s, $0.0150):

```
OK
```

### code

**kimi-via-claude** (10.4s, $0.0075):

```
def is_palindrome(s):     return s == s[::-1]
```

**mimo-via-claude** (8.1s, $0.0120):

```
```python def is_palindrome(s):     return s == s[::-1] ```
```

**deepseek-via-claude** (FAILED):

```
subprocess timeout after 90.0s
```

### reasoning

**kimi-via-claude** (8.9s, $0.0072):

```
Mergesort is O(n log n) because it recursively splits the array into halves, creating log n levels of recursion, and then merges all elements back together at each level, doing O(n) work per level.
```

**mimo-via-claude** (12.0s, $0.0129):

```
Merge sort is O(n log n) because it recursively divides the array in half (producing log n levels of recursion) and performs a linear-time O(n) merge at each level, giving O(n) Ã— O(log n) = O(n log n
```

**deepseek-via-claude** (16.1s, $0.0133):

```
Merge sort recursively divides the array in half (log n levels) and at each level performs a linear merge of all elements (O(n)), yielding O(n log n) total time.
```

### long_context

**kimi-via-claude** (23.5s, $0.0294):

```
The Fenwick tree array is initialized with length `n` instead of `n + 1`, so the 1-based update loop writes past the end of the array when it reaches index `n`.
```

**mimo-via-claude** (12.4s, $0.0236):

```
The Fenwick tree uses 1-based indexing, but the tree is allocated with only `n` elements instead of `n + 1`, causing an `IndexError` when `fenwick_update` tries to access index 10 (since `len(tree)` i
```

**deepseek-via-claude** (48.7s, $0.0431):

```
The Fenwick tree array is allocated with size `n` (10) instead of `n + 1` (11), so the update for index `n` is silently dropped because the while-loop condition `i < len(tree)` is false when `i == n`,
```

### multimodal_probe

**kimi-via-claude** (FAILED):

```
subprocess timeout after 90.0s
```

**mimo-via-claude** (FAILED):

```
subprocess timeout after 90.0s
```

**deepseek-via-claude** (FAILED):

```
subprocess timeout after 90.0s
```
