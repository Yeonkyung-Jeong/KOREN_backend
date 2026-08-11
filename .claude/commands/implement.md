---
description: Researcher → Planner → Reviewer 순서로 구현을 진행하는 워크플로우. 각 단계 사이 사람 승인 체크포인트 포함.
argument-hint: <구현할 태스크 설명>
---

다음 태스크에 대해 Researcher → Planner → (구현) → Reviewer 순서로 작업을
진행하세요. 각 단계가 끝나면 반드시 사람의 승인을 받은 뒤에만 다음 단계로
넘어가세요. 절대 단계를 건너뛰거나 승인 없이 진행하지 마세요.

태스크: $ARGUMENTS

## 서브에이전트 호출 방법 (중요)

Claude Code의 알려진 버그로 인해 프로젝트 커스텀 서브에이전트
(`.claude/agents/*.md`)가 Task/Agent 도구의 `subagent_type`으로 인식되지
않고 "Agent type not found" 에러가 발생하는 경우가 있다. 따라서 아래
Researcher/Planner/Reviewer 단계에서는 `subagent_type: researcher` 등으로
직접 호출을 시도하지 말고, 매번 다음 절차를 따르라:

1. 해당 역할의 정의 파일(`.claude/agents/researcher.md`,
   `.claude/agents/planner.md`, `.claude/agents/reviewer.md` 중 하나)을
   Read 도구로 읽는다.
2. YAML frontmatter(`---`로 둘러싸인 부분)를 제외한 본문, 즉 역할 지시문
   전체를 그대로 가져온다.
3. Agent 도구를 `subagent_type: general-purpose`로 호출하면서, 프롬프트
   맨 앞에 그 역할 지시문 원문을 그대로 삽입하고, 이어서 이번 단계에서
   실제로 조사/계획/검토해야 할 태스크 내용(및 이전 단계 산출물)을
   붙여넣는다. 즉 매 호출마다 "너는 이 프로젝트의 Researcher/Planner/
   Reviewer다"라는 역할 지시문을 프롬프트에 명시적으로 포함시켜 그 역할을
   수행하게 만든다.
4. frontmatter의 `tools:` 목록(Researcher/Planner는 Read, Grep, Glob;
   Reviewer는 Read, Grep, Glob, Bash)은 해당 역할이 코드를 수정하지 않고
   조사/계획/검토만 수행해야 한다는 제약을 뜻하므로, general-purpose
   에이전트에게도 프롬프트에서 "코드를 수정하지 말 것. Write/Edit 도구를
   사용하지 말 것"을 명시적으로 지시한다.

## 진행 순서

1. **Researcher 호출**
   - 위 절차대로 `.claude/agents/researcher.md`의 지시문을 읽어 주입한
     general-purpose 에이전트를 호출해 위 태스크를 조사시키세요.
   - 결과 리포트를 사람에게 그대로 보여주세요.
   - AskUserQuestion으로 "이 조사 내용을 바탕으로 계획 단계로 넘어갈까요?"를
     물으세요. 승인이 아니면(수정 요청 등) 그 피드백을 반영해 Researcher
     역할을 다시 호출하고, 다시 승인을 받을 때까지 반복하세요.

2. **Planner 호출**
   - 승인된 Researcher 리포트와 원래 태스크를 함께 넘겨, 위 절차대로
     `.claude/agents/planner.md`의 지시문을 주입한 general-purpose 에이전트를
     호출하세요.
   - 결과 계획(체크리스트)을 사람에게 그대로 보여주세요.
   - AskUserQuestion으로 "이 계획대로 구현을 시작할까요?"를 물으세요. 승인이
     아니면 피드백을 반영해 Planner 역할을 다시 호출하고, 승인받을 때까지
     반복하세요.
   - 계획에 사람의 판단이 필요하다고 명시된 지점이 있다면, 구현을 시작하기
     전에 먼저 그 지점들을 사람에게 확인하세요.

3. **구현**
   - 승인된 계획에 따라 직접 코드를 작성하세요(계획에 없는 범위 확장 금지).
   - 계획에 포함된 유닛 테스트도 함께 작성하세요.
   - 구현이 끝나면 변경사항(diff)을 간단히 요약해 사람에게 보여주고,
     Reviewer 단계로 넘어가는 데 승인을 받으세요.

4. **Reviewer 호출**
   - 위 절차대로 `.claude/agents/reviewer.md`의 지시문을 주입한
     general-purpose 에이전트를 호출하세요. Planner의 계획 원문과 구현된
     diff, 그리고 실행해야 할 유닛 테스트를 함께 전달하세요.
   - 결과("통과" 또는 "반려(이유)")를 사람에게 그대로 보여주세요.
   - "반려"인 경우: 반려 이유를 사람에게 보여주고 어떻게 처리할지 물으세요
     (직접 수정 후 Reviewer 재호출 / Planner로 되돌아가기 / 종료 중 선택).
     사람이 명시적으로 다음 행동을 정하기 전에는 임의로 재작업하지 마세요.
   - "통과"인 경우: 최종 요약을 사람에게 보고하고 워크플로우를 종료하세요.

## 규칙

- 각 체크포인트에서 사람의 명시적 승인 없이 절대 다음 단계로 넘어가지
  마세요.
- 서브에이전트 역할(researcher/planner/reviewer)은 코드를 수정하지
  않습니다. 실제 코드 작성은 3단계(구현)에서 메인 에이전트가 직접
  수행하세요.
- 각 단계 결과는 요약하지 말고 사람이 판단할 수 있도록 충분한 원문 그대로
  보여주세요.
