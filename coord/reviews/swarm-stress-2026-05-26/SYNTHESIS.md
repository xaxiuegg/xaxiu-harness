# Swarm stress test — 2026-05-26

## Phase 1: concurrency curve

Per-backend dispatch metrics at N = 4, 8, 16, 32 concurrent.
Realistic short prompts (code / reasoning / JSON / bullet).

| Backend | N | OK | Fail | 429s | Wall | p50 | p95 | max | Speedup |
|---|---|---|---|---|---|---|---|---|---|
| `claude-mimo` | 4 | 4 | 0 | 0 | 30s | 29.9s | 30.3s | 30.3s | 3.9× |
| `claude-mimo` | 8 | 8 | 0 | 0 | 28s | 25.8s | 28.4s | 28.4s | 7.3× |
| `claude-mimo` | 16 | 16 | 0 | 0 | 48s | 41.9s | 47.8s | 48.0s | 13.9× |
| `claude-mimo` | 32 | 32 | 0 | 0 | 64s | 56.9s | 60.4s | 64.0s | 27.4× |
| `claude-kimi` | 4 | 4 | 0 | 0 | 23s | 20.7s | 22.9s | 23.0s | 3.5× |
| `claude-kimi` | 8 | 8 | 0 | 0 | 36s | 30.5s | 36.3s | 36.3s | 6.8× |
| `claude-kimi` | 16 | 16 | 0 | 0 | 52s | 40.0s | 51.7s | 52.0s | 12.6× |
| `claude-kimi` | 32 | 32 | 0 | 0 | 66s | 54.5s | 66.1s | 66.1s | 26.6× |
| `claude-deepseek` | 4 | 4 | 0 | 0 | 16s | 15.0s | 16.2s | 16.2s | 3.7× |
| `claude-deepseek` | 8 | 8 | 0 | 0 | 27s | 24.3s | 26.9s | 27.0s | 7.4× |
| `claude-deepseek` | 16 | 16 | 0 | 0 | 39s | 37.7s | 39.5s | 39.5s | 15.0× |
| `claude-deepseek` | 32 | 32 | 0 | 0 | 59s | 55.1s | 58.3s | 58.8s | 29.6× |
| `deepseek` | 4 | 4 | 0 | 0 | 16s | 14.2s | 16.1s | 16.1s | 3.5× |
| `deepseek` | 8 | 8 | 0 | 0 | 30s | 22.5s | 29.6s | 29.6s | 6.3× |
| `deepseek` | 16 | 16 | 0 | 0 | 37s | 31.3s | 37.2s | 37.2s | 13.8× |
| `deepseek` | 32 | 32 | 0 | 0 | 47s | 37.1s | 44.2s | 46.7s | 25.9× |

## Per-backend headline

| Backend | Highest N tested | OK at that N | p95 at that N | Throttled? |
|---|---|---|---|---|
| `claude-mimo` | 32 | 32/32 | 60.4s | no |
| `claude-kimi` | 32 | 32/32 | 66.1s | no |
| `claude-deepseek` | 32 | 32/32 | 58.3s | no |
| `deepseek` | 32 | 32/32 | 44.2s | no |

## Phase 2: mixed-backend parallel panel

Fired 12 packets across 3 backends in parallel.
Wall: 39s.  Success: 12/12.

| Backend | OK | Avg latency | Max latency |
|---|---|---|---|
| `claude-mimo` | 4/4 | 35.7s | 39.1s |
| `claude-kimi` | 4/4 | 35.9s | 37.5s |
| `claude-deepseek` | 4/4 | 31.8s | 32.8s |

## Verdict

- Overall success: 240/240 (100%) across all concurrency levels
- Rate-limit indicators: 0 dispatches showed 429/throttle markers in stderr
- **Conclusion: swarm handles 32-way concurrency cleanly** with no observable throttling.  Audit-panel concern ("concurrency >10x untested") closed.