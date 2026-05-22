"""Sequential 2-engine review of infra smoke results.

MiMo Pro + DeepSeek (skip Kimi K2.6 — keeps timing out on long-form gen).
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

PACKET = Path("coord/reviews/external/infra_smoke_compact.md")
OUT_DIR = Path("coord/reviews/external")


@dataclass(frozen=True)
class Reviewer:
    label: str
    engine: str
    model: str


REVIEWERS: list[Reviewer] = [
    Reviewer("mimo-pro",          "mimo",     "mimo-v2.5-pro"),
    Reviewer("deepseek-thinking", "deepseek", "deepseek-v4-flash"),
]


def main() -> int:
    if not PACKET.exists():
        print(f"packet missing: {PACKET}", file=sys.stderr)
        return 1
    text = PACKET.read_text(encoding="utf-8")
    print(f"packet: {len(text)} chars", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results: list[dict] = []

    for rv in REVIEWERS:
        print(f"\n[review] {rv.label} ({rv.engine}/{rv.model})...", flush=True)
        eng = get_engine(rv.engine, prefer_dpapi=False)
        started = time.monotonic()
        try:
            resp = eng.dispatch(text, rv.model, {"max_tokens": 4000})
            latency = int((time.monotonic() - started) * 1000)
            ok = bool(resp.success and (resp.text or "").strip())
            body = resp.text or ""
            err = resp.error
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            ok, body, err = False, "", f"{type(exc).__name__}: {exc}"

        out = OUT_DIR / f"{stamp}_infra_review_{rv.label}.md"
        if ok:
            out.write_text(
                f"<!-- engine={rv.engine} model={rv.model} success=True latency_ms={latency} -->\n\n{body}",
                encoding="utf-8")
            print(f"  ✓ {latency}ms ({len(body)} chars) → {out}", flush=True)
            results.append({"label": rv.label, "ok": True,
                            "latency_ms": latency, "chars": len(body),
                            "path": str(out)})
        else:
            out.write_text(f"FAILED latency_ms={latency} error={err}\n", encoding="utf-8")
            print(f"  ✗ {latency}ms error={err}", flush=True)
            results.append({"label": rv.label, "ok": False, "latency_ms": latency,
                            "error": err, "path": str(out)})

    (OUT_DIR / f"infra_review_manifest_{stamp}.json").write_text(
        json.dumps({"run_at_utc": datetime.now(timezone.utc).isoformat(),
                    "packet_chars": len(text), "results": results}, indent=2),
        encoding="utf-8")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
