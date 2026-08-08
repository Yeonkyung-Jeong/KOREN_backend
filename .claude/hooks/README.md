# Claude Code 프롬프트/도구 로깅

이 프로젝트에서 실행되는 Claude Code 세션의 사용자 프롬프트와 도구 실행을
`logs/claude_hooks.jsonl`에 JSON Lines 형식으로 append 기록한다.

## 목적

- 디버깅: 결과가 이상할 때 "요청 자체가 모호했는지" vs "Claude Code가 도구를
  잘못/이상하게 썼는지"를 로그로 구분해 원인 파악
- 재현성: 나중에 "왜 이렇게 구현했는지"를 로그로 다시 추적
- 문서화 재료: Researcher/Planner/Reviewer 워크플로우(`.claude/agents/`,
  `.claude/commands/implement.md`)에서 각 단계가 실제로 뭘 조사·계획·검증했는지
  사후 추측 없이 로그 근거로 문서화
- 실행 추적성: AI 도구를 블랙박스로 쓰지 않고 요청/실행을 추적 가능하게 설계

## 동작 방식

- `.claude/settings.json`에 등록된 3개 hook이 이 프로젝트 디렉토리에서 실행되는
  세션에서만 동작한다 (Claude Code 전체 세션이 아니라 이 프로젝트 로컬).
- 각 hook은 `.claude/hooks/log_event.py <event_type>`을 실행하며, Claude Code가
  hook 표준입력으로 넘기는 JSON payload를 읽어 한 줄짜리 이벤트 레코드로
  변환해 `logs/claude_hooks.jsonl`에 append한다.
- 로깅 자체는 세션 동작을 절대 막지 않도록 모든 예외를 무시하고 항상 종료 코드
  0으로 끝난다(`log_event.py`).
- `logs/`는 `.gitignore`에 등록되어 있어 커밋되지 않는다.

| Hook 이벤트        | event_type | 기록 시점        |
|--------------------|------------|-------------------|
| UserPromptSubmit   | `prompt`   | 사용자가 프롬프트를 제출한 직후 |
| PreToolUse         | `pre_tool` | 도구 실행 직전     |
| PostToolUse        | `post_tool`| 도구 실행 직후     |

## 로그 스키마

`logs/claude_hooks.jsonl`의 각 줄은 하나의 JSON 오브젝트다. 공통 필드:

| 필드         | 타입           | 설명                                              |
|--------------|----------------|---------------------------------------------------|
| `timestamp`  | string (ISO 8601, timezone 포함) | 이벤트 기록 시각                    |
| `event_type` | string         | `"prompt"` \| `"pre_tool"` \| `"post_tool"`        |
| `session_id` | string \| null | Claude Code 세션 ID (동일 세션 이벤트를 묶을 때 사용) |

### `event_type: "prompt"`

| 필드     | 타입   | 설명              |
|----------|--------|-------------------|
| `prompt` | string | 사용자 프롬프트 원문 |

### `event_type: "pre_tool"`

| 필드         | 타입   | 설명                     |
|--------------|--------|--------------------------|
| `tool_name`  | string | 실행하려는 도구 이름      |
| `tool_input` | object | 도구에 전달된 인자(그대로) |

### `event_type: "post_tool"`

| 필드             | 타입    | 설명                                                    |
|------------------|---------|---------------------------------------------------------|
| `tool_name`      | string  | 실행된 도구 이름                                          |
| `tool_input`     | object  | 도구에 전달된 인자                                        |
| `success`        | boolean | `tool_response.error`가 없으면 true                       |
| `result_summary` | string  | `tool_response`를 JSON 문자열화한 요약 (최대 1000자, 초과 시 `...(truncated)`) |
| `error`          | string  | `success`가 false일 때만 존재, 에러 내용                    |

### 예시

```jsonl
{"timestamp": "2026-08-09T02:14:08+09:00", "event_type": "prompt", "session_id": "abc123", "prompt": "..."}
{"timestamp": "2026-08-09T02:14:09+09:00", "event_type": "pre_tool", "session_id": "abc123", "tool_name": "Edit", "tool_input": {"file_path": "app/routers.py", "old_string": "...", "new_string": "..."}}
{"timestamp": "2026-08-09T02:14:09+09:00", "event_type": "post_tool", "session_id": "abc123", "tool_name": "Edit", "tool_input": {"file_path": "app/routers.py"}, "success": true, "result_summary": "{\"filePath\": \"app/routers.py\"}"}
```

## 파싱 방법 (Python 예시)

```python
import json

with open("logs/claude_hooks.jsonl", encoding="utf-8") as f:
    events = [json.loads(line) for line in f if line.strip()]

# 세션별로 시간순 재구성
by_session: dict[str, list[dict]] = {}
for e in events:
    by_session.setdefault(e["session_id"], []).append(e)
```

## 파일 구성

- `.claude/settings.json` — hook 등록 (UserPromptSubmit / PreToolUse / PostToolUse)
- `.claude/hooks/log_event.py` — 실제 로깅 스크립트
- `logs/claude_hooks.jsonl` — 로그 파일 (gitignore됨, 로컬 전용)
