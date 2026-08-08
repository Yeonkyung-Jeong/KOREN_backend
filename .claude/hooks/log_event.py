#!/usr/bin/env python3
"""Claude Code hook script: append UserPromptSubmit / PreToolUse / PostToolUse
events for this project's sessions to logs/claude_hooks.jsonl (JSON Lines).

Registered in .claude/settings.json, invoked as:
    python .claude/hooks/log_event.py <event_type>
with the hook's JSON payload on stdin. See .claude/hooks/README.md for the
log schema.

Logging must never break the session: all errors are swallowed and the
process always exits 0.
"""
import sys
import os
import json
import datetime

MAX_SUMMARY_CHARS = 1000


def project_root() -> str:
    # this file lives at <root>/.claude/hooks/log_event.py
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read_payload() -> dict:
    # Read raw bytes and decode as UTF-8 explicitly: on Windows, sys.stdin's
    # default encoding follows the console codepage (e.g. cp949), which
    # corrupts non-ASCII (Korean) prompt text piped in as UTF-8.
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_unparsed_stdin": raw}


def build_record(event_type: str, payload: dict) -> dict:
    record = {
        "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "event_type": event_type,
        "session_id": payload.get("session_id"),
    }

    if event_type == "prompt":
        record["prompt"] = payload.get("prompt", "")

    elif event_type == "pre_tool":
        record["tool_name"] = payload.get("tool_name")
        record["tool_input"] = payload.get("tool_input")

    elif event_type == "post_tool":
        tool_response = payload.get("tool_response")
        error = tool_response.get("error") if isinstance(tool_response, dict) else None

        summary = json.dumps(tool_response, ensure_ascii=False, default=str)
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS] + "...(truncated)"

        record["tool_name"] = payload.get("tool_name")
        record["tool_input"] = payload.get("tool_input")
        record["success"] = error is None
        record["result_summary"] = summary
        if error:
            record["error"] = error

    return record


def main() -> None:
    event_type = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    payload = read_payload()
    record = build_record(event_type, payload)

    log_dir = os.path.join(project_root(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "claude_hooks.jsonl")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
