# logs/claude_hooks.jsonl을 사람이 읽기 좋은 한 줄 포맷(시간 - 이벤트타입 - 요약)으로
# 콘솔에 출력한다. --session으로 특정 세션만 필터링할 수 있다.
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = REPO_ROOT / "logs" / "claude_hooks.jsonl"

# tool_input에서 요약으로 쓸 값을 우선순위대로 탐색
INPUT_SUMMARY_KEYS = ("command", "file_path", "pattern", "query", "skill", "subject", "description", "prompt")


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())  # 개행/연속 공백 정리
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def summarize_tool_input(tool_input) -> str:
    if not isinstance(tool_input, dict) or not tool_input:
        return ""
    for key in INPUT_SUMMARY_KEYS:
        if tool_input.get(key):
            return truncate(str(tool_input[key]), 80)
    key, value = next(iter(tool_input.items()))
    return truncate(f"{key}={value}", 80)


def summarize_result(result_summary) -> str:
    if not result_summary:
        return ""
    try:
        obj = json.loads(result_summary) if isinstance(result_summary, str) else result_summary
    except (TypeError, ValueError):
        return truncate(str(result_summary), 100)

    if isinstance(obj, dict):
        if "stdout" in obj or "stderr" in obj:
            text = (obj.get("stdout") or "").strip() or (obj.get("stderr") or "").strip()
            return truncate(text, 100)
        file_info = obj.get("file")
        if isinstance(file_info, dict) and file_info.get("content"):
            return truncate(file_info["content"], 100)
        return truncate(json.dumps(obj, ensure_ascii=False), 100)
    return truncate(str(obj), 100)


def format_event(event: dict) -> str:
    timestamp = event.get("timestamp", "?")
    event_type = event.get("event_type", "?")
    tool_name = event.get("tool_name")

    if event_type == "prompt":
        summary = truncate(event.get("prompt", ""), 120)
    elif event_type == "pre_tool":
        summary = f"{tool_name} -> {summarize_tool_input(event.get('tool_input'))}"
    elif event_type == "post_tool":
        status = "OK" if event.get("success") else "FAIL"
        input_summary = summarize_tool_input(event.get("tool_input"))
        result_summary = summarize_result(event.get("result_summary"))
        summary = f"{tool_name} [{status}] {input_summary} :: {result_summary}"
    else:
        summary = truncate(json.dumps(event, ensure_ascii=False), 150)

    return f"{timestamp} - {event_type} - {summary}"


def iter_events(log_path: Path, session_id: str | None):
    with log_path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(f"[view_logs] {line_no}번째 줄 JSON 파싱 실패, 스킵", file=sys.stderr)
                continue
            if session_id and not str(event.get("session_id", "")).startswith(session_id):
                continue
            yield event


def main():
    # Windows 콘솔(cp949 등)에서 한글 출력이 깨지거나 UnicodeEncodeError로 죽는 것을 방지
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="logs/claude_hooks.jsonl을 사람이 읽기 좋게 출력한다.")
    parser.add_argument("--session", help="이 값으로 시작하는 session_id를 가진 이벤트만 출력 (부분 입력 가능)")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help="로그 파일 경로 (기본: logs/claude_hooks.jsonl)")
    args = parser.parse_args()

    log_path = Path(args.log_path)
    if not log_path.exists():
        print(f"[view_logs] 로그 파일을 찾을 수 없습니다: {log_path}", file=sys.stderr)
        sys.exit(1)

    count = 0
    try:
        for event in iter_events(log_path, args.session):
            print(format_event(event))
            count += 1
    except (BrokenPipeError, OSError):
        # `| head` 등으로 출력을 조기에 끊었을 때 발생하는 예외를 조용히 무시
        sys.exit(0)

    if count == 0:
        print("[view_logs] 조건에 맞는 이벤트가 없습니다.", file=sys.stderr)


if __name__ == "__main__":
    main()
