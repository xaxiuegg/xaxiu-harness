# Pattern B intensive smoke-test matrix - RESULTS

**Date**: 2026-05-26
**Total dispatches**: 15 (3 engines x 5 categories)
**Success rate**: 15/15 (100%)
**Elapsed**: 50s wall-clock
**Total cost**: $0.2318

## Per-engine summary

| Engine | Categories OK | Total tokens out | Total cost | Avg latency |
|---|---|---|---|---|
| `kimi-via-claude` | 5/5 | 1406 | $0.0681 | 18.0s |
| `mimo-via-claude` | 5/5 | 596 | $0.0754 | 9.3s |
| `deepseek-via-claude` | 5/5 | 608 | $0.0883 | 10.0s |

## Full matrix

| Engine | Category | OK | Latency | In | Out | Cost | Output excerpt |
|---|---|---|---|---|---|---|---|
| `kimi-via-claude` | trivial | ok | 8.3s | 74 | 47 | $0.0039 | OK |
| `kimi-via-claude` | code | ok | 12.0s | 94 | 110 | $0.0057 | ```python def is_palindrome(s):     return s == s[::-1] ``` |
| `kimi-via-claude` | reasoning | ok | 9.1s | 849 | 227 | $0.0107 | Mergesort recursively splits the input in half logâ‚‚ n times and performs O(n) comparison-copy work per level to merge  |
| `kimi-via-claude` | long_context | ok | 49.9s | 1777 | 907 | $0.0419 | The tree array is allocated with length n instead of n+1, so the 1-based Fenwick indexing cannot accommodate the element |
| `kimi-via-claude` | multimodal_probe | ok | 10.5s | 90 | 115 | $0.0059 | No image is accessible in our conversation. If you have a system architecture diagram you'd like me to describe, please  |
| `mimo-via-claude` | trivial | ok | 6.8s | 1880 | 19 | $0.0115 | OK |
| `mimo-via-claude` | code | ok | 8.0s | 1898 | 47 | $0.0114 | ```python def is_palindrome(s):     return s == s[::-1] ``` |
| `mimo-via-claude` | reasoning | ok | 10.9s | 1885 | 169 | $0.0148 | Merge sort recursively splits the list into two halves (producing logâ‚‚n levels) and then linearly merges the sorted ha |
| `mimo-via-claude` | long_context | ok | 9.2s | 2739 | 144 | $0.0215 | The Fenwick tree is 1-based but allocated with only `n=10` elements (indices 0â€“9), so the loop calling `fenwick_update |
| `mimo-via-claude` | multimodal_probe | ok | 11.6s | 1908 | 217 | $0.0161 | No image was provided or is accessible in this conversation. There is no attached image file, no image data, and no file |
| `deepseek-via-claude` | trivial | ok | 7.5s | 1699 | 29 | $0.0092 | OK |
| `deepseek-via-claude` | code | ok | 9.4s | 1719 | 43 | $0.0132 | ```python def is_palindrome(s):     return s == s[::-1] ``` |
| `deepseek-via-claude` | reasoning | ok | 10.1s | 1707 | 70 | $0.0162 | Mergesort is O(n log n) because it recursively divides the array into halves (log n levels of splitting) and at each lev |
| `deepseek-via-claude` | long_context | ok | 11.6s | 2769 | 247 | $0.0295 | The Fenwick tree array is allocated with length `n` instead of `n+1`, so the 1-indexed access pattern (indices 1 through |
| `deepseek-via-claude` | multimodal_probe | ok | 11.4s | 1715 | 219 | $0.0201 | I don't see any image attached to your message â€” there's no diagram, screenshot, or image file present in this convers |

## Per-category outputs (compare engine answers)

### trivial

**kimi-via-claude** (8.3s, $0.0039):

```
OK
```

**mimo-via-claude** (6.8s, $0.0115):

```
OK
```

**deepseek-via-claude** (7.5s, $0.0092):

```
OK
```

### code

**kimi-via-claude** (12.0s, $0.0057):

```
```python def is_palindrome(s):     return s == s[::-1] ```
```

**mimo-via-claude** (8.0s, $0.0114):

```
```python def is_palindrome(s):     return s == s[::-1] ```
```

**deepseek-via-claude** (9.4s, $0.0132):

```
```python def is_palindrome(s):     return s == s[::-1] ```
```

### reasoning

**kimi-via-claude** (9.1s, $0.0107):

```
Mergesort recursively splits the input in half logâ‚‚ n times and performs O(n) comparison-copy work per level to merge the sorted subarrays, yielding O(n log n) total time.
```

**mimo-via-claude** (10.9s, $0.0148):

```
Merge sort recursively splits the list into two halves (producing logâ‚‚n levels) and then linearly merges the sorted halves at each level, so the total work grows as nâ€¯Ã—â€¯logâ€¯n.
```

**deepseek-via-claude** (10.1s, $0.0162):

```
Mergesort is O(n log n) because it recursively divides the array into halves (log n levels of splitting) and at each level merges all elements together (n work per level).
```

### long_context

**kimi-via-claude** (49.9s, $0.0419):

```
The tree array is allocated with length n instead of n+1, so the 1-based Fenwick indexing cannot accommodate the element at position n.
```

**mimo-via-claude** (9.2s, $0.0215):

```
The Fenwick tree is 1-based but allocated with only `n=10` elements (indices 0â€“9), so the loop calling `fenwick_update(tree, i, ...)` up to `i=10` produces an `IndexError` since index 10 is out of b
```

**deepseek-via-claude** (11.6s, $0.0295):

```
The Fenwick tree array is allocated with length `n` instead of `n+1`, so the 1-indexed access pattern (indices 1 through n) causes an off-by-one out-of-bounds error on the last update or query.
```

### multimodal_probe

**kimi-via-claude** (10.5s, $0.0059):

```
No image is accessible in our conversation. If you have a system architecture diagram you'd like me to describe, please attach or paste it, and I'll be happy to analyze and explain what it shows.
```

**mimo-via-claude** (11.6s, $0.0161):

```
No image was provided or is accessible in this conversation. There is no attached image file, no image data, and no file path pointing to an image in your message. I can only analyze images that are d
```

**deepseek-via-claude** (11.4s, $0.0201):

```
I don't see any image attached to your message â€” there's no diagram, screenshot, or image file present in this conversation for me to examine. I can only see the text of your request.  If you intend
```
