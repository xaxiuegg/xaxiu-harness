"""W14-ASK-AUDIT 2026-05-27: producer→auditor prompt template + parser
for ``harness ask --audit``.

The audit prompt asks a SECOND engine to critique a producer engine's
answer in a STRUCTURED way (VERDICT / CORRECTIONS / MISSED / OVERALL)
so the verdict is programmatically actionable: a CI gate can fail on
``FAIL``, an operator tool can highlight CORRECTIONS, etc.

Design notes
============

- The rubric is rigid by design.  Downstream consumers need
  predictable structure; free-form critique defeats the point of a
  programmatic audit primitive.

- The free-form OVERALL section is included so the auditor can speak
  naturally when the rigid fields don't quite fit a particular case.

- Full producer response is included verbatim (no truncation).  The
  cost stays bounded because typical producer responses are
  500-2000 tokens out → ~$0.01-0.02 of input cost on the auditor's
  side at current Pattern B rates.

- The audit prompt template is checked-in source.  The operator can
  grep this file any time to see exactly what stage 2 is being asked.
  (Operator directive 2026-05-20: every prompt should be inspectable.)

- ``parse_audit_verdict`` is forgiving — case-insensitive headers,
  tolerant of minor LLM formatting drift.  A missing or malformed
  VERDICT is surfaced as ``"UNKNOWN"`` so callers can react rather
  than silently treating it as PASS.
"""

from __future__ import annotations

import re


_AUDIT_TEMPLATE = """\
You are auditing another engine's answer to the question below.

Your job: judge whether the candidate answer is correct, complete, and
well-reasoned.  Hallucinations, factual errors, important omissions, and
dangerously overstated claims are all in scope.

Source-trace rule — do NOT judge on plausibility alone:
- For each specific claim in the candidate answer, verify it against the
  source material included in the question (code, quoted text, data), or
  against your own knowledge when no source is provided.
- A claim that extrapolates a pattern to a new target ("X has the same
  risk/behavior as Y") WITHOUT citing the target's own evidence, and that
  you cannot verify from the provided material, is a FALSE POSITIVE:
  list it under CORRECTIONS prefixed "FALSE POSITIVE:" and name the
  category error.
- If a load-bearing claim is unverifiable from the material given, say
  so under CORRECTIONS rather than letting it pass.

QUESTION:
{question}

CANDIDATE ANSWER (from {producer_engine}):
{producer_response}

Return your audit in this EXACT structure (the labels are load-bearing
- downstream tools parse them):

VERDICT: PASS | PARTIAL | FAIL
ONE-LINE SUMMARY: <up to 20 words explaining the verdict>
CORRECTIONS: <specific factual or logical errors, bullet list, or "none">
MISSED CONSIDERATIONS: <important points the candidate did not address, or "none">
OVERALL: <one paragraph, why this verdict>

Verdict scale:
  PASS    - the answer is correct and adequately complete.
  PARTIAL - mostly correct but with notable omissions or minor errors.
  FAIL    - factually wrong, dangerously misleading, or off-topic.

Do not include any other prose before VERDICT or after OVERALL.
"""


def build_audit_prompt(
    question: str,
    producer_engine: str,
    producer_response: str,
) -> str:
    """Format the audit prompt with the question + producer's response.

    The producer response is NOT truncated.  The auditor needs the
    full text to spot factual issues; truncation hurts most exactly
    where audits matter most (long nuanced answers).
    """
    return _AUDIT_TEMPLATE.format(
        question=question.strip(),
        producer_engine=producer_engine,
        producer_response=producer_response.strip(),
    )


# Section parsers.  Each captures from its label to the next known
# section header (or EOF), tolerant of header variants ("ONE-LINE
# SUMMARY" vs "ONE LINE SUMMARY", "MISSED" vs "MISSED CONSIDERATIONS").
_VERDICT_RE = re.compile(
    r"VERDICT\s*:\s*(PASS|PARTIAL|FAIL)\b",
    re.IGNORECASE,
)
# Section-header alternation that matches "MISSED" OR "MISSED CONSIDERATIONS"
# — LLMs use both.  Used inside lookaheads to terminate the previous section.
_NEXT_HEADER = r"(?:CORRECTIONS|MISSED(?:\s+CONSIDERATIONS)?|OVERALL)"

_SUMMARY_RE = re.compile(
    r"ONE[- ]LINE\s+SUMMARY\s*:\s*(.*?)" + r"(?=\n\s*" + _NEXT_HEADER + r"\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_CORRECTIONS_RE = re.compile(
    r"CORRECTIONS\s*:\s*(.*?)" + r"(?=\n\s*(?:MISSED(?:\s+CONSIDERATIONS)?|OVERALL)\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_MISSED_RE = re.compile(
    r"MISSED(?:\s+CONSIDERATIONS)?\s*:\s*(.*?)"
    r"(?=\n\s*OVERALL\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_OVERALL_RE = re.compile(
    r"OVERALL\s*:\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)


def parse_audit_verdict(text: str) -> dict:
    """Extract structured fields from an auditor response.

    Returns a dict with keys: ``verdict``, ``summary``, ``corrections``,
    ``missed``, ``overall``, ``raw``.  Missing or malformed VERDICT is
    surfaced as ``"UNKNOWN"`` so callers can react instead of silently
    treating it as PASS.  Other missing sections are empty strings.

    The parser is forgiving — case-insensitive, tolerant of "ONE LINE
    SUMMARY" vs "ONE-LINE SUMMARY", "MISSED" vs "MISSED CONSIDERATIONS".
    If the auditor returned pure free-form prose with no recognizable
    structure, all structured fields will be empty + verdict is
    ``"UNKNOWN"``, and ``raw`` preserves the full text for the operator
    to inspect.
    """
    text = text or ""

    m = _VERDICT_RE.search(text)
    verdict = m.group(1).upper() if m else "UNKNOWN"

    def _extract(regex: "re.Pattern[str]") -> str:
        m = regex.search(text)
        if not m:
            return ""
        return m.group(1).strip()

    return {
        "verdict": verdict,
        "summary": _extract(_SUMMARY_RE),
        "corrections": _extract(_CORRECTIONS_RE),
        "missed": _extract(_MISSED_RE),
        "overall": _extract(_OVERALL_RE),
        "raw": text,
    }
