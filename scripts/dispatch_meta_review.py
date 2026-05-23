"""3-engine meta-review of session structure via DIRECT engine.dispatch.

Bypasses dispatch_packet entirely (which auto-fallbacks across the whole
engine chain even with force_engine set, plus runs an adapter-load step
that adds friction for a one-shot review).  Goes straight to the
concrete engine HTTP path with a generous read timeout.

Sequential one-at-a-time — parallel hit engine rate-limits earlier.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


PACKET = Path("coord/reviews/external/session_arc_compact.md")
OUT_DIR = Path("coord/reviews/external")


@dataclass(frozen=True)
class Reviewer:
    label: str
    engine: str
    model: str


REVIEWERS: list[Reviewer] = [
    Reviewer(label="kimi-k2.6",          engine="kimi",     model="kimi-for-coding"),
    Reviewer(label="mimo-pro",           engine="mimo",     model="mimo-v2.5-pro"),
    Reviewer(label="deepseek-thinking",  engine="deepseek", model="deepseek-v4-flash"),
]


def main() -> int:
    if not PACKET.exists():
        print(f"[review] packet missing: {PACKET}", file=sys.stderr)
        return 1
    packet_text = PACKET.read_text(encoding="utf-8")
    print(f"[review] packet: {len(packet_text)} chars", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    stamp_dir = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for rv in REVIEWERS:
        print(f"\n[review] {rv.label} ({rv.engine}/{rv.model})...", flush=True)
        engine = get_engine(rv.engine, prefer_dpapi=False)
        started = time.monotonic()
        try:
            # W5-W 2026-05-23: don't cap max_tokens; engine defaults apply.
            resp = engine.dispatch(packet_text, rv.model, {})
            latency = int((time.monotonic() - started) * 1000)
            ok = bool(resp.success and (resp.text or "").strip())
            text = resp.text or ""
            error = resp.error
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            ok = False
            text = ""
            error = f"{type(exc).__name__}: {exc}"

        out_path = OUT_DIR / f"{stamp_dir}_review_{rv.label}.md"
        if ok:
            out_path.write_text(
                f"<!-- engine={rv.engine} model={rv.model} success=True "
                f"latency_ms={latency} chars={len(text)} -->\n\n{text}",
                encoding="utf-8",
            )
            print(f"  ✓ {latency}ms  ({len(text)} chars)  → {out_path}", flush=True)
            results.append({"label": rv.label, "ok": True, "latency_ms": latency,
                            "chars": len(text), "path": str(out_path)})
        else:
            out_path.write_text(
                f"FAILED engine={rv.engine} model={rv.model} latency_ms={latency} "
                f"error={error}\n",
                encoding="utf-8",
            )
            print(f"  ✗ {latency}ms  error={error}", flush=True)
            results.append({"label": rv.label, "ok": False, "latency_ms": latency,
                            "error": error, "path": str(out_path)})

    manifest = OUT_DIR / f"manifest_{stamp_dir}.json"
    manifest.write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "packet_chars": len(packet_text),
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\n[review] manifest: {manifest}", flush=True)
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
