"""Extract a digestible session arc from a Claude Code transcript JSONL.

Reduces a ~19MB raw transcript to ~30-60KB of:
  - Every user message (verbatim)
  - Every assistant message (text body excerpt, max 400 chars per turn)
  - Tool calls (name + brief input shape, no full output)
  - Final stats: turn count, commit count grep, etc.

Output suitable as input to a 5-agent review.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path


def extract(transcript_path: Path, out_path: Path,
            max_assistant_chars: int = 400) -> dict:
    """Read JSONL transcript, write compact arc to out_path, return stats."""
    user_count = 0
    assistant_count = 0
    tool_counter: Counter = Counter()
    arc_lines: list[str] = []
    user_messages_verbatim: list[str] = []

    with open(transcript_path, "r", encoding="utf-8") as f:
        for line_idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = obj.get("type")
            # Standard Claude Code transcript shape: {"type": "user"|"assistant", "message": {...}}
            message = obj.get("message") or {}
            content = message.get("content")

            if role == "user":
                user_count += 1
                # content may be a list (with tool_result blocks) or a string
                text_parts: list[str] = []
                if isinstance(content, str):
                    text_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif block.get("type") == "tool_result":
                                # Skip tool results — too verbose
                                continue
                user_text = "\n".join(t for t in text_parts if t.strip())
                # Skip system-reminders, hook-feedback noise (start with markers)
                if user_text.startswith("<system-reminder>") or user_text.startswith("<command-message>"):
                    continue
                if not user_text.strip():
                    continue
                user_messages_verbatim.append(user_text.strip())
                arc_lines.append(f"\n=== USER TURN {user_count} ===")
                arc_lines.append(user_text.strip())

            elif role == "assistant":
                assistant_count += 1
                text_parts: list[str] = []
                tool_calls_this_turn: list[str] = []
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tn = block.get("name", "?")
                            tool_counter[tn] += 1
                            # Brief description of tool call
                            inp = block.get("input") or {}
                            brief = ""
                            if tn == "Bash":
                                cmd = inp.get("command", "")
                                brief = cmd[:80]
                            elif tn in ("Edit", "Write"):
                                brief = str(inp.get("file_path", ""))
                            elif tn == "Read":
                                brief = str(inp.get("file_path", ""))
                            elif tn == "Grep":
                                brief = f"pattern={inp.get('pattern','')[:40]}"
                            else:
                                brief = str(list(inp.keys())[:3])
                            tool_calls_this_turn.append(f"  → {tn}: {brief}")
                assistant_text = "\n".join(t for t in text_parts if t.strip())
                arc_lines.append(f"\n--- assistant turn {assistant_count} ---")
                if assistant_text:
                    excerpt = assistant_text[:max_assistant_chars]
                    if len(assistant_text) > max_assistant_chars:
                        excerpt += f"... [+{len(assistant_text) - max_assistant_chars} chars]"
                    arc_lines.append(excerpt)
                if tool_calls_this_turn:
                    arc_lines.append(f"  [{len(tool_calls_this_turn)} tool calls]")
                    for tc in tool_calls_this_turn[:10]:  # cap at 10 per turn
                        arc_lines.append(tc)
                    if len(tool_calls_this_turn) > 10:
                        arc_lines.append(f"  → ... +{len(tool_calls_this_turn) - 10} more")

    header = [
        f"# Session arc summary",
        f"",
        f"Transcript: {transcript_path}",
        f"User turns: {user_count}",
        f"Assistant turns: {assistant_count}",
        f"Top tool calls:",
    ]
    for tn, c in tool_counter.most_common(10):
        header.append(f"  - {tn}: {c}")
    header.append("")
    header.append("## All operator directives (verbatim user messages):")
    header.append("")
    for i, um in enumerate(user_messages_verbatim, start=1):
        header.append(f"### Operator message {i}")
        header.append(um)
        header.append("")
    header.append("\n---\n")
    header.append("## Full turn-by-turn arc")
    header.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(header + arc_lines), encoding="utf-8",
    )
    return {
        "user_turns": user_count,
        "assistant_turns": assistant_count,
        "tool_calls": dict(tool_counter.most_common(20)),
        "out_path": str(out_path),
        "out_size_bytes": out_path.stat().st_size,
    }


def make_compact(transcript_path: Path, out_path: Path) -> dict:
    """W5-TT compact version: only operator directives + commit-log
    digest, sized for MiMo's 131K input cap (~50KB target).
    """
    user_count = 0
    assistant_count = 0
    user_messages: list[str] = []
    tool_counter: Counter = Counter()
    bash_commits: list[str] = []

    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = obj.get("type")
            message = obj.get("message") or {}
            content = message.get("content")

            if role == "user":
                user_count += 1
                text_parts: list[str] = []
                if isinstance(content, str):
                    text_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                ut = "\n".join(t for t in text_parts if t.strip()).strip()
                if not ut:
                    continue
                if ut.startswith("<system-reminder>") or ut.startswith("<command-message>"):
                    continue
                # Skip operator's tool-result-only messages (no text)
                user_messages.append(ut)

            elif role == "assistant":
                assistant_count += 1
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            t = block.get("type")
                            if t == "tool_use":
                                tn = block.get("name", "?")
                                tool_counter[tn] += 1
                                # Capture git-commit lines for the digest
                                if tn == "Bash":
                                    cmd = (block.get("input") or {}).get("command", "")
                                    if "git commit -m" in cmd:
                                        # Extract the first commit-message line via heredoc detection
                                        m = re.search(
                                            r"(?:'EOF'|EOF)[\s\n]+([^\n]+)",
                                            cmd,
                                        )
                                        if m:
                                            bash_commits.append(m.group(1).strip())

    sections = [
        "# Session arc — compact review input (W5-TT)",
        "",
        f"Transcript: {transcript_path}",
        f"User turns: {user_count}",
        f"Assistant turns: {assistant_count}",
        "",
        "## Tool-call frequency (top 15)",
        "",
    ]
    for tn, c in tool_counter.most_common(15):
        sections.append(f"- {tn}: {c}")
    sections.append("")
    sections.append("## Commit messages observed (first line each)")
    sections.append("")
    for c in bash_commits[:60]:
        sections.append(f"- {c}")
    sections.append("")
    sections.append(f"## All operator messages verbatim ({len(user_messages)} total)")
    sections.append("")
    for i, um in enumerate(user_messages, start=1):
        sections.append(f"### Operator #{i}")
        sections.append(um.strip())
        sections.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(sections)
    out_path.write_text(body, encoding="utf-8")
    return {
        "user_messages": len(user_messages),
        "user_turns": user_count,
        "assistant_turns": assistant_count,
        "commits_seen": len(bash_commits),
        "out_path": str(out_path),
        "out_size_bytes": out_path.stat().st_size,
    }


def main() -> int:
    transcript = Path(
        r"C:\Users\xaxiu\.claude\projects\D--Projects\5edcc857-3ec7-47cc-b834-752b1ab2dfe8.jsonl"
    )
    if not transcript.exists():
        print(f"transcript not found: {transcript}", file=sys.stderr)
        return 1
    # Compact (for MiMo review)
    compact = Path("coord/reviews/session_arc_compact.md")
    cstats = make_compact(transcript, compact)
    print("compact:", json.dumps(cstats, indent=2))
    # Full (for archive / human reading)
    full = Path("coord/reviews/session_arc_full.md")
    fstats = extract(transcript, full)
    print("full:   ", json.dumps(fstats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
