# Pattern B intensive smoke-test matrix - RESULTS

**Date**: 2026-05-26
**Total dispatches**: 15 (3 engines x 5 categories)
**Success rate**: 15/15 (100%)
**Elapsed**: 76s wall-clock
**Total cost**: $0.1637

## Per-engine summary

| Engine | Categories OK | Total tokens out | Total cost | Avg latency |
|---|---|---|---|---|
| `kimi-via-claude` | 5/5 | 2136 | $0.0757 | 29.8s |
| `mimo-via-claude` | 5/5 | 299 | $0.0334 | 10.9s |
| `deepseek-via-claude` | 5/5 | 591 | $0.0546 | 5.0s |

## Full matrix

| Engine | Category | OK | Latency | In | Out | Cost | Output excerpt |
|---|---|---|---|---|---|---|---|
| `kimi-via-claude` | trivial | ok | 10.9s | 357 | 33 | $0.0032 | OK |
| `kimi-via-claude` | code | ok | 20.5s | 121 | 221 | $0.0070 | ```python def is_palindrome(s):     return s == s[::-1] ``` |
| `kimi-via-claude` | reasoning | ok | 22.4s | 108 | 226 | $0.0070 | Mergesort is O(n log n) because it recursively splits the input in half logâ‚‚ n times and performs O(n) work merging th |
| `kimi-via-claude` | long_context | ok | 76.5s | 1548 | 1442 | $0.0518 | The Fenwick tree array is initialized with n elements instead of n plus one, so the one-based indexing used by the updat |
| `kimi-via-claude` | multimodal_probe | ok | 18.9s | 117 | 214 | $0.0068 | No image is accessible. I cannot see any diagram or image in your message. If you can share the image directly (by uploa |
| `mimo-via-claude` | trivial | ok | 8.3s | 426 | 19 | $0.0045 | OK |
| `mimo-via-claude` | code | ok | 8.3s | 444 | 24 | $0.0035 | ```python def is_palindrome(s):     return s == s[::-1] ``` |
| `mimo-via-claude` | reasoning | ok | 13.2s | 431 | 61 | $0.0049 | Mergesort is O(n log n) because it recursively splits the array into halves (producing logâ‚‚ n levels) and then perform |
| `mimo-via-claude` | long_context | ok | 13.1s | 1273 | 86 | $0.0143 | The tree array is allocated with only 10 elements (indices 0â€“9), but the Fenwick tree functions use 1-based indexing u |
| `mimo-via-claude` | multimodal_probe | ok | 11.6s | 442 | 109 | $0.0062 | No image is attached to or accessible from your message. I can only see your text â€” there's no diagram, screenshot, or |
| `deepseek-via-claude` | trivial | ok | 3.9s | 450 | 25 | $0.0029 | OK |
| `deepseek-via-claude` | code | ok | 5.8s | 470 | 109 | $0.0091 | ```python def is_palindrome(s):     return s == s[::-1] ``` |
| `deepseek-via-claude` | reasoning | ok | 6.3s | 458 | 152 | $0.0105 | Mergesort achieves O(n log n) because it recursively divides the input in half log n times, and at each of those levels  |
| `deepseek-via-claude` | long_context | ok | 5.1s | 1520 | 198 | $0.0228 | The tree array is sized `n` instead of `n+1`, so the update at index `n` (10) writes out of bounds, and the query return |
| `deepseek-via-claude` | multimodal_probe | ok | 4.0s | 466 | 107 | $0.0093 | I don't see any image attached to your message. The prompt references "(image: system architecture)" but no image file o |

## Per-category outputs (compare engine answers)

### trivial

**kimi-via-claude** (10.9s, $0.0032):

```
OK
```

**mimo-via-claude** (8.3s, $0.0045):

```
OK
```

**deepseek-via-claude** (3.9s, $0.0029):

```
OK
```

### code

**kimi-via-claude** (20.5s, $0.0070):

```
```python def is_palindrome(s):     return s == s[::-1] ```
```

**mimo-via-claude** (8.3s, $0.0035):

```
```python def is_palindrome(s):     return s == s[::-1] ```
```

**deepseek-via-claude** (5.8s, $0.0091):

```
```python def is_palindrome(s):     return s == s[::-1] ```
```

### reasoning

**kimi-via-claude** (22.4s, $0.0070):

```
Mergesort is O(n log n) because it recursively splits the input in half logâ‚‚ n times and performs O(n) work merging the sorted halves at each level.
```

**mimo-via-claude** (13.2s, $0.0049):

```
Mergesort is O(n log n) because it recursively splits the array into halves (producing logâ‚‚ n levels) and then performs a linear-time merge at each level, resulting in n Ã— log n total work.
```

**deepseek-via-claude** (6.3s, $0.0105):

```
Mergesort achieves O(n log n) because it recursively divides the input in half log n times, and at each of those levels it merges the subarrays in linear O(n) time, yielding n * log n total operations
```

### long_context

**kimi-via-claude** (76.5s, $0.0518):

```
The Fenwick tree array is initialized with n elements instead of n plus one, so the one-based indexing used by the update and query functions accesses an out-of-bounds index when processing the nth el
```

**mimo-via-claude** (13.1s, $0.0143):

```
The tree array is allocated with only 10 elements (indices 0â€“9), but the Fenwick tree functions use 1-based indexing up to index 10, so `fenwick_update` will write past the end of the array; the fix
```

**deepseek-via-claude** (5.1s, $0.0228):

```
The tree array is sized `n` instead of `n+1`, so the update at index `n` (10) writes out of bounds, and the query returns an incorrect partial sum.
```

### multimodal_probe

**kimi-via-claude** (18.9s, $0.0068):

```
No image is accessible. I cannot see any diagram or image in your message. If you can share the image directly (by uploading it), Iâ€™ll be happy to describe what it shows.
```

**mimo-via-claude** (11.6s, $0.0062):

```
No image is attached to or accessible from your message. I can only see your text â€” there's no diagram, screenshot, or file for me to examine.  If you'd like me to analyze a system architecture diag
```

**deepseek-via-claude** (4.0s, $0.0093):

```
I don't see any image attached to your message. The prompt references "(image: system architecture)" but no image file or data is present in the conversation.  Please attach the diagram image and I'll
```
