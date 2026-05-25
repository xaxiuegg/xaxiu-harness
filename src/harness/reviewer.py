"""W12-B-INSTANT-REVIEW: `harness review <file>` — multi-engine document review.

Bottles the Aquinas 3-engine review flow (commit feeb446 demonstrated it)
into a single repeatable CLI verb.  Drop any text/markdown/PDF document
on the harness, get back:
  - One review per configured engine (default: kimi + deepseek + mimo)
  - A synthesis Markdown summarizing convergent + divergent findings
  - All artifacts written to coord/reviews/<basename>/

Operator promise: $0 cost for the default 3-engine config (Kimi + MiMo
are subscription; DeepSeek's per-call cost is fractions of a cent and
absorbed silently).  Wall-clock 2-5 minutes for documents up to ~20
pages.

Design choices:
  - Document text extraction is best-effort: TXT/MD as-is, PDF via
    pypdf.  Other formats (DOCX, XLSX, HTML) raise a clear error
    pointing at conversion tools.
  - Three default lenses (correctness, security, realism) cover the
    common review request shape.  --lens-set is the customization knob.
  - Engines dispatched in parallel via ThreadPoolExecutor.
  - max_tokens defaults to 6000 per the operator's high-cap directive
    (commit feeb446: W12-B-MAX-TOKENS-DEFAULT-RAISE).
"""
from __future__ import annotations

import concurrent.futures as _cf
import dataclasses
import re
import time
from pathlib import Path
from typing import Callable

from harness.engines.concrete import get_engine

# -- text extraction ---------------------------------------------------------

_TXT_SUFFIXES = {".txt", ".md", ".markdown", ".py", ".js", ".ts",
                  ".java", ".c", ".cpp", ".rs", ".go", ".rb",
                  ".json", ".yaml", ".yml", ".toml", ".html", ".htm",
                  ".css", ".sh", ".bat", ".ps1", ".sql", ".csv",
                  ".tsv", ".log"}


def extract_text(path: Path) -> str:
    """Read *path* and return its text content.

    Raises:
        FileNotFoundError if path doesn't exist
        ValueError with a remediation hint for unsupported formats
    """
    if not path.exists():
        raise FileNotFoundError(f"{path}")
    suffix = path.suffix.lower()
    if suffix in _TXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _extract_pdf(path)
    raise ValueError(
        f"unsupported file type {suffix!r}.  "
        f"Convert to .md / .txt / .pdf first, or use a tool like "
        f"`pandoc` for .docx and `libreoffice --headless --convert-to pdf` "
        f"for .xlsx / .pptx."
    )


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF review requires pypdf.  Run: pip install pypdf"
        ) from exc
    reader = PdfReader(str(path))
    parts: list[str] = []
    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            text = f"[page {i} extract failed: {exc}]"
        parts.append(f"\n--- page {i} ---\n{text}")
    return "".join(parts)


# -- lenses ------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Lens:
    """One review lens — defines engine + persona prompt."""
    id: str
    engine: str
    model: str
    prompt: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Lens.id must be non-empty")


# Three sensible defaults that mirror the Aquinas review pattern.
DEFAULT_LENSES: list[Lens] = [
    Lens(
        id="correctness-and-integrity",
        engine="kimi",
        model="kimi-for-coding",
        prompt=(
            "You are a careful technical reviewer focused on internal "
            "correctness, factual claims, and consistency. Look for "
            "internal contradictions, unsupported claims, debug artifacts "
            "leaking into the document, math/code errors, and signs of "
            "copy-paste-without-understanding. Output 5-8 specific findings, "
            "each with a verbatim grounding quote from the document. End with "
            "a one-sentence honest verdict."
        ),
    ),
    Lens(
        id="technical-and-security",
        engine="deepseek",
        model="deepseek-v4-flash",
        prompt=(
            "You are a senior software + security reviewer. Audit the "
            "TECHNICAL ACCURACY (math, code, architectural soundness) and "
            "SECURITY POSTURE (auth, input validation, attack surface, data "
            "flow). Severity-tag each finding LOW/MED/HIGH/CRITICAL. Output "
            "4-6 technical findings and 4-6 security findings, each with a "
            "verbatim grounding quote. End with a one-sentence ship-readiness "
            "verdict."
        ),
    ),
    Lens(
        id="purpose-and-realism",
        engine="mimo",
        model="mimo-v2.5-pro",
        prompt=(
            "You are a realism + scope reviewer. Is this a coherent project "
            "the author could plausibly build + understand, or buzzwords "
            "stitched together? What's plausibly real vs aspirational? Output "
            "4-6 realism findings, each with a verbatim quote. End with: "
            "(a) what's plausibly real, (b) what's aspirational, (c) what to "
            "ask the author to demonstrate live."
        ),
    ),
]


# -- auto-default helpers (W13 Tier 1 Shift A + F) --------------------------

# Suffix -> lens-set name.  Source files default to code-review; prose
# files default to doc-review; everything else falls back to the
# 3-engine general "default" set.  Operator can override with explicit
# lens_set / --lens-set on every call.
_CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c",
                   ".cpp", ".cc", ".h", ".hpp", ".rs", ".go", ".rb",
                   ".php", ".cs", ".swift", ".kt", ".sh", ".bat",
                   ".ps1", ".sql", ".lua", ".r", ".m"}
_DOC_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".pdf",
                  ".html", ".htm"}


def infer_lens_set(path: Path | str) -> str:
    """Pick a lens-set name from the file extension.

    W13 Tier 1 Shift A: auto-default so agents calling
    ``harness.review()`` don't have to learn the lens-set vocabulary
    before they get useful output.  Source files (.py/.js/.ts/...) ->
    'code-review'; prose files (.md/.txt/.pdf/...) -> 'doc-review';
    unknown extensions -> 'default' (3-engine general review).
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in _CODE_SUFFIXES:
        return "code-review"
    if suffix in _DOC_SUFFIXES:
        return "doc-review"
    return "default"


# W13 Tier 1 Shift F: safe-floor max_tokens.  4000 keeps multi-paragraph
# reviews intact (the 2000 prior default frequently truncated mid-finding,
# noted by the master audit + operator's 2026-05-24 high-cap directive).
SAFE_MAX_TOKENS_FLOOR = 4000
QUICK_MAX_TOKENS = 1000


def auto_max_tokens(*, quick: bool = False,
                     override: int | None = None) -> int:
    """Resolve max_tokens with safe floor + --quick opt-down.

    Precedence:
      1. Explicit ``override`` int (e.g. CLI ``--max-tokens 8000``) wins.
      2. ``quick=True`` selects ``QUICK_MAX_TOKENS`` (fast preview).
      3. Otherwise the safe floor ``SAFE_MAX_TOKENS_FLOOR``.

    Designed so an agent calling ``harness.review(path)`` with no
    keyword args gets quality-by-default; a deliberate ``quick=True``
    is the only way to drop below the floor without an explicit number.
    """
    if override is not None:
        return int(override)
    if quick:
        return QUICK_MAX_TOKENS
    return SAFE_MAX_TOKENS_FLOOR


# Alternative lens sets the operator can pick via --lens-set
LENS_SETS: dict[str, list[Lens]] = {
    "default": DEFAULT_LENSES,
    "code-review": [
        Lens(
            id="bugs-and-edge-cases",
            engine="kimi", model="kimi-for-coding",
            prompt=(
                "You are a senior code reviewer. Find bugs, race conditions, "
                "off-by-ones, missing error handling, unhandled edge cases. "
                "For each issue: file:line if shown, the problem, the fix, "
                "severity LOW/MED/HIGH. Be specific and actionable."
            ),
        ),
        Lens(
            id="security-and-injection",
            engine="deepseek", model="deepseek-v4-flash",
            prompt=(
                "Security review. Find injection vectors (SQL, command, "
                "path, format-string), unsafe deserialization, missing input "
                "validation, secret leakage, missing auth checks. Severity "
                "tag each finding."
            ),
        ),
        Lens(
            id="readability-and-architecture",
            engine="mimo", model="mimo-v2.5-pro",
            prompt=(
                "Architecture + readability review. Is the abstraction "
                "level right? Are names clear? Are there opportunities to "
                "simplify? Where does the code make the next reader's job "
                "harder than it needs to be?"
            ),
        ),
    ],
    "doc-review": [
        Lens(
            id="clarity-and-structure",
            engine="kimi", model="kimi-for-coding",
            prompt=(
                "Documentation review focused on CLARITY + STRUCTURE. "
                "Where does the reader get lost? What's missing for a "
                "first-time reader? What's redundant for an experienced "
                "reader? Suggest 5-8 specific edits."
            ),
        ),
        Lens(
            id="accuracy-and-completeness",
            engine="deepseek", model="deepseek-v4-flash",
            prompt=(
                "Fact-check + completeness review. Are claims accurate? "
                "Are critical caveats / failure modes missing? Are examples "
                "correct and runnable? Flag every dubious assertion."
            ),
        ),
        Lens(
            id="audience-fit",
            engine="mimo", model="mimo-v2.5-pro",
            prompt=(
                "Audience-fit review. Who is this for? Does the level + "
                "tone + jargon match that audience? What would a different "
                "audience misread?"
            ),
        ),
    ],
}


# -- dispatch ---------------------------------------------------------------


@dataclasses.dataclass
class LensResult:
    lens: Lens
    ok: bool
    text: str = ""
    error: str = ""
    elapsed_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


def _dispatch_lens(lens: Lens, document_text: str,
                    max_tokens: int = 6000,
                    document_label: str = "the document") -> LensResult:
    """Run one lens against the document.  Never raises."""
    started = time.monotonic()
    full_prompt = (
        f"{lens.prompt}\n\n"
        f"---\n\n"
        f"## {document_label} (verbatim)\n\n"
        f"{document_text}\n"
    )
    try:
        eng = get_engine(lens.engine, prefer_dpapi=False)
    except RuntimeError as exc:
        return LensResult(lens=lens, ok=False,
                           error=f"engine init failed: {exc}",
                           elapsed_s=time.monotonic() - started)
    try:
        resp = eng.dispatch(full_prompt, lens.model,
                             {"max_tokens": max_tokens})
    except Exception as exc:
        return LensResult(lens=lens, ok=False,
                           error=f"dispatch raised: {type(exc).__name__}: {exc}",
                           elapsed_s=time.monotonic() - started)
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        return LensResult(lens=lens, ok=False,
                           error=f"engine returned empty/error: {resp.error}",
                           elapsed_s=elapsed)
    return LensResult(lens=lens, ok=True, text=resp.text.strip(),
                       elapsed_s=elapsed, tokens_in=resp.tokens_in,
                       tokens_out=resp.tokens_out,
                       cost_usd=resp.cost_usd)


def review_document(document_path: Path,
                     lenses: list[Lens] | None = None,
                     max_tokens: int = 6000,
                     out_dir: Path | None = None,
                     max_concurrent: int = 3,
                     progress_cb: Callable[[str], None] | None = None,
                     ) -> dict:
    """Run a multi-lens review against *document_path*.

    Args:
        document_path: TXT / MD / PDF (or other code text formats).
        lenses: review lenses; defaults to DEFAULT_LENSES (3 engines).
        max_tokens: per-engine output cap (default 6000 per the
            high-cap directive 2026-05-24).
        out_dir: where to write artifacts.  Defaults to
            coord/reviews/<document_basename>/.
        max_concurrent: parallel engine dispatches.
        progress_cb: optional callback(str) for progress lines.

    Returns:
        Dict with: results (list[LensResult]), out_dir, synthesis_path,
        document_text_length, elapsed_s, total_cost_usd.
    """
    if lenses is None:
        lenses = DEFAULT_LENSES
    if not lenses:
        raise ValueError("at least one lens required")
    document_path = Path(document_path).resolve()
    document_text = extract_text(document_path)

    if out_dir is None:
        from harness._constants import _REPO_ROOT
        # Sanitize basename for use as a directory name
        slug = re.sub(r"[^a-zA-Z0-9_-]", "-", document_path.stem)[:64]
        out_dir = _REPO_ROOT / "coord" / "reviews" / f"review-{slug}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _log(line: str) -> None:
        if progress_cb is not None:
            progress_cb(line)

    started = time.monotonic()
    _log(f"document: {document_path.name} ({len(document_text)} chars)")
    _log(f"lenses: {len(lenses)} engines, max_concurrent={max_concurrent}, "
         f"max_tokens={max_tokens}")

    results: list[LensResult] = []
    document_label = document_path.name
    with _cf.ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        futures = {
            pool.submit(_dispatch_lens, lens, document_text, max_tokens,
                         document_label): lens
            for lens in lenses
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = "OK" if r.ok else "FAIL"
            extra = (f"{r.elapsed_s:.1f}s "
                     f"{r.tokens_in}/{r.tokens_out}t "
                     f"${r.cost_usd:.4f}" if r.ok
                     else r.error[:80])
            _log(f"[{flag}] {r.lens.id:<32} {r.lens.engine:<10} {extra}")
            results.append(r)

    # Write per-lens artifacts
    for r in results:
        path = out_dir / f"{r.lens.engine}_{r.lens.id}.md"
        if r.ok:
            path.write_text(r.text, encoding="utf-8")
        else:
            path.write_text(
                f"# {r.lens.id} ({r.lens.engine}) — FAILED\n\n{r.error}\n",
                encoding="utf-8",
            )

    # Synthesis
    synthesis_path = out_dir / "SYNTHESIS.md"
    synthesis = _render_synthesis(document_path, results)
    synthesis_path.write_text(synthesis, encoding="utf-8")

    elapsed = time.monotonic() - started
    total_cost = round(sum(r.cost_usd for r in results), 6)
    _log(f"synthesis: {synthesis_path}")
    _log(f"total: {len(results)} lenses in {elapsed:.0f}s, "
         f"${total_cost:.4f} spent")

    return {
        "results": results,
        "out_dir": out_dir,
        "synthesis_path": synthesis_path,
        "document_text_length": len(document_text),
        "elapsed_s": elapsed,
        "total_cost_usd": total_cost,
    }


def _render_synthesis(document_path: Path,
                       results: list[LensResult]) -> str:
    """Render a SYNTHESIS.md aggregating the per-lens reviews."""
    from datetime import datetime, timezone
    lines: list[str] = []
    lines.append(f"# Multi-engine review: {document_path.name}")
    lines.append("")
    lines.append(f"**Generated**: "
                 f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}")
    lines.append(f"**Document**: `{document_path}`")
    lines.append("")
    lines.append("**Lenses dispatched**:")
    for r in results:
        status = "OK" if r.ok else "FAIL"
        lines.append(
            f"- `{r.lens.id}` via **{r.lens.engine}** "
            f"({r.elapsed_s:.0f}s, {r.tokens_in}/{r.tokens_out} tokens, "
            f"${r.cost_usd:.4f}) — {status}"
        )
    total_cost = sum(r.cost_usd for r in results)
    n_ok = sum(1 for r in results if r.ok)
    lines.append("")
    lines.append(f"**Total cost**: ${total_cost:.4f} "
                 f"({n_ok}/{len(results)} engines succeeded)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-lens reviews")
    lines.append("")
    for r in results:
        lines.append(f"### {r.lens.id} (via {r.lens.engine})")
        lines.append("")
        if r.ok:
            lines.append(r.text)
        else:
            lines.append(f"_Engine returned an error: {r.error}_")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Cross-engine notes")
    lines.append("")
    lines.append(
        "Read each lens above for the engine-specific findings.  Look for "
        "**convergent findings** (flagged by 2+ lenses) — those carry the "
        "strongest signal.  **Divergent findings** (flagged by only one "
        "lens) are often the most novel but should be verified against the "
        "document independently."
    )
    return "\n".join(lines) + "\n"
