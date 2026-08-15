# app/agent/nodes.py
# 8개 그래프 노드. PRD §9.3에 대응하되, create_agent의 단일 ReAct 루프가 아니라
# 역할이 분리된 노드 + 조건부 엣지로 재작성/평가/재시도 흐름을 구성한다.
import os
from datetime import date
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from app.agent.schemas import (
    AnswerGrade,
    AnswerResponse,
    ChatResponseEnvelope,
    DocumentGrade,
    RewrittenQuery,
    RouteDecision,
)
from app.agent.state import AgentState
from app.agent.tools import retrieve_patient_history

LLM_MODEL = "gpt-4o-mini"
# grade_answer는 "이 진단은 없다"류의 부재 진술이 컨텍스트에 근거하는지를 판단해야
# 하는데, gpt-4o-mini는 동의어 표현(예: "상체" vs "torso")까지 과도하게 엄격하게
# 근거 부족으로 오판하는 경향이 있었다(수동 QA에서 확인). 가드레일의 최종
# 안전판이므로 여기만 더 큰 모델을 쓴다.
GRADING_LLM_MODEL = "gpt-4o"


@lru_cache
def _get_llm() -> ChatOpenAI:
    # 모듈 임포트 시점이 아니라 최초 노드 실행 시점에 생성 — OPENAI_API_KEY가
    # 없어도(예: routing.py 단위 테스트) 이 모듈을 임포트할 수 있게 하기 위함.
    return ChatOpenAI(model=LLM_MODEL, api_key=os.getenv("OPENAI_API_KEY"), temperature=0)


@lru_cache
def _get_grading_llm() -> ChatOpenAI:
    return ChatOpenAI(model=GRADING_LLM_MODEL, api_key=os.getenv("OPENAI_API_KEY"), temperature=0)


ROUTE_QUERY_SYSTEM_PROMPT = (
    "당신은 피부과 의사용 '환자 히스토리 브리핑 어시스턴트'의 라우팅 게이트입니다. "
    "의사의 최신 메시지에 답하기 위해 환자 진단 이력 또는 유사 사례 검색이 필요한지만 "
    "판단하세요.\n"
    "- needs_retrieval=true로 판단해야 하는 경우: 환자의 특정 부위/시기/증상에 대한 "
    "진단 이력을 묻는 질문(예: '두피 쪽도 본 적 있어?', '작년에도 왔었나?'), 전체 이력 "
    "브리핑 요청, 유사 사례 질문 등 — 이번 대화에서 아직 그 정보를 검색해서 제공한 적이 "
    "없다면 항상 검색이 필요합니다. 그 결과가 '없음/해당 없음'으로 나올 것 같다는 짐작만으로 "
    "검색을 생략하지 마세요 — '없음'도 검색해서 확인해야 하는 사실입니다.\n"
    "- needs_retrieval=false로 판단해야 하는 경우: 인사말, 이미 이번 대화에서 검색해 "
    "제공한 결과에 대한 단순 재확인/재요약 요청뿐입니다.\n"
    "검색이 필요하다면, 메시지가 검색 쿼리로 쓰기에 너무 짧거나 모호한지도 함께 판단하세요. "
    "검색 필요 여부가 애매하면 needs_retrieval=true를 선택하세요(불필요한 검색보다 근거 "
    "없는 답변이 더 위험합니다)."
)


def route_query(state: AgentState, config: RunnableConfig) -> dict:
    """검색 필요 여부(및 재작성 필요 여부)만 가볍게 판단하는 게이트 노드.

    "브리핑이냐 유사사례냐 일반질문이냐" 같은 세부 의도는 여기서 분류하지
    않는다 — 그 판단은 retrieve 노드(scope 선택)와 generate 노드(3종 응답
    스키마 선택)에서 자연스럽게 이루어진다. 이 노드는 오직 "검색이 필요한가
    (Y/N)"만 보는 가벼운 게이트로 남겨, 규칙 기반 사전 분기보다 LLM이 매
    턴 유연하게 판단하게 한다.
    """
    decision: RouteDecision = (
        _get_llm()
        .with_structured_output(RouteDecision, method="function_calling")
        .invoke([SystemMessage(content=ROUTE_QUERY_SYSTEM_PROMPT), *state["messages"]])
    )
    return {"needs_retrieval": decision.needs_retrieval, "needs_rewrite": decision.needs_rewrite}


REWRITE_QUERY_SYSTEM_PROMPT = (
    "의사의 메시지를 진단 이력 검색에 적합한, 구체적이고 명확한 한국어 검색 질의로 "
    "재작성하세요. 환자 이름 등 검색과 무관한 정보는 제외하고, 부위/기간/증상 등 "
    "검색에 도움이 되는 단서를 살리세요."
)


def rewrite_query(state: AgentState, config: RunnableConfig) -> dict:
    """검색 질의가 모호/간결할 때 재작성하는 노드. grade_documents의 재시도 지시로도 재진입한다.

    scope(this_patient/similar_patients) 선택은 이 노드의 책임이 아니다 —
    질의 텍스트만 검색에 적합하게 다듬고, 실제 scope 판단은 retrieve
    노드에서 LLM이 bind_tools로 직접 채운다. rewrite_count는 여기서
    증가시킨다(무한 루프 방지 카운터, PRD §9.3).
    """
    messages = [SystemMessage(content=REWRITE_QUERY_SYSTEM_PROMPT), *state["messages"]]
    if state.get("doc_grade_reasoning"):
        messages.append(
            SystemMessage(
                content=f"[이전 검색 결과 평가] {state['doc_grade_reasoning']} 이 점을 고려해 질의를 다시 작성하세요."
            )
        )
    rewritten: RewrittenQuery = _get_llm().with_structured_output(RewrittenQuery, method="function_calling").invoke(messages)
    return {
        "query_text": rewritten.rewritten_query_text,
        "rewrite_count": state["rewrite_count"] + 1,
    }


RETRIEVE_SYSTEM_PROMPT = (
    "retrieve_patient_history 도구를 호출해 검색을 수행하세요. "
    "환자 본인의 진단 이력 브리핑이나 특정 이력 질문("
    "예: '최근 이력 브리핑', '두피 쪽도 본 적 있어?')이면 scope='this_patient'를, "
    "다른 환자의 비슷한 사례를 찾는 질문(예: '비슷한 케이스 있어?')이면 "
    "scope='similar_patients'를 선택하세요. query_text에는 검색 의도를 담은 질의를 "
    "그대로 넣으세요.\n"
    "scope='similar_patients'이고 질의가 특정 부위를 명시하면(예: '하지 부위', "
    "'팔 쪽', '몸통에 난 것', '두피/목') anatomy_site를 반드시 해당 값으로 채우세요 "
    "— 두경부/얼굴/두피/목→head_neck, 팔/손/상지→upper_extremity, "
    "다리/발/하지→lower_extremity, 몸통/등/가슴/배→torso. 부위가 명시되지 않았으면 "
    "비워 두세요."
)


def retrieve(state: AgentState, config: RunnableConfig) -> dict:
    """LLM이 bind_tools로 scope/query_text를 채워 retrieve_patient_history를 호출하는 노드.

    일반적인 ReAct 에이전트처럼 ToolNode/실행 루프를 거치지 않고, 이 노드가
    직접 도구를 호출하고 결과를 state에 담아 다음 노드로 넘긴다 — 이
    그래프에는 "도구를 계속 호출할지 말지"를 LLM이 스스로 결정하는 반복
    루프가 없고, retrieve는 항상 정확히 한 번만 호출되는 단일 스텝이기
    때문이다. tool_choice로 도구 호출을 강제하는 것도 같은 이유(이 노드에
    도달했다는 것 자체가 이미 검색이 필요하다고 route_query가 확정했다는
    뜻이므로, 호출 여부를 다시 LLM이 고민할 필요가 없다).
    """
    llm_with_tool = _get_llm().bind_tools(
        [retrieve_patient_history], tool_choice="retrieve_patient_history"
    )
    ai_message: AIMessage = llm_with_tool.invoke(
        [SystemMessage(content=RETRIEVE_SYSTEM_PROMPT), HumanMessage(content=state["query_text"])]
    )
    tool_call = ai_message.tool_calls[0]

    tool_config: RunnableConfig = {
        "configurable": {
            "patient_pk": state["patient_pk"],
            "db_session": config["configurable"]["db_session"],
        }
    }
    docs = retrieve_patient_history.invoke(tool_call["args"], config=tool_config)

    return {"retrieved_docs": docs, "retrieval_scope": tool_call["args"]["scope"]}


GRADE_DOCUMENTS_SYSTEM_PROMPT = (
    "검색 질의와 검색 결과를 비교해, 결과가 질의에 답하기에 충분히 관련성 있고 "
    "개수가 확보되어 있는지 평가하세요. 결과가 비어있거나 질의와 무관하면 "
    "불충분(is_sufficient=false)으로 판단하세요."
)


def grade_documents(state: AgentState, config: RunnableConfig) -> dict:
    """검색 결과의 적합성을 평가하고, 불충분하면 재시도 카운터를 증가시키는 노드.

    this_patient 스코프는 query_text와 무관하게 환자 본인의 전체 진단 이력을
    그대로 반환하는 확정적 SQL 조회이므로(PRD §9.2), "질의와 관련된 항목이
    없다"는 이유로 불충분 판정을 내리면 재작성을 반복해도 결과가 절대 바뀌지
    않아 무의미한 루프가 된다. "해당 이력이 없다"는 사실 자체가 generate가
    전체 이력에서 도출해야 할 정답이므로, 이 스코프는 결과가 비어있지 않으면
    항상 충분한 것으로 결정적으로 판단한다. LLM 평가는 실제로 관련성이
    불확실한 similar_patients(벡터 검색) 결과에만 적용한다.
    """
    docs = state.get("retrieved_docs", [])
    scope = state.get("retrieval_scope")

    if not docs:
        grade = DocumentGrade(is_sufficient=False, reasoning="검색 결과가 0건입니다.")
    elif scope == "this_patient":
        grade = DocumentGrade(is_sufficient=True, reasoning="환자 본인의 전체 진단 이력을 확보함.")
    else:
        grade: DocumentGrade = (
            _get_llm()
            .with_structured_output(DocumentGrade, method="function_calling")
            .invoke(
                [
                    SystemMessage(content=GRADE_DOCUMENTS_SYSTEM_PROMPT),
                    HumanMessage(content=f"질의: {state['query_text']}\n\n검색 결과:\n{docs}"),
                ]
            )
        )

    update: dict = {
        "doc_grade_sufficient": grade.is_sufficient,
        "doc_grade_reasoning": grade.reasoning,
    }
    return update


def context_organizer(state: AgentState, config: RunnableConfig) -> dict:
    """검색 결과를 generate 노드가 바로 근거로 쓸 수 있는 문자열로 정리하는 순수 포매팅 노드.

    retrieve의 결과(list[dict])는 이미 SQL/벡터 검색으로 구조화되어 있어
    LLM이 다시 요약할 필요가 없다 — 오히려 LLM 요약을 한 단계 더 거치면
    비용·지연이 늘고, 이 단계에서부터 원문이 왜곡될 위험(할루시네이션)이
    생긴다. 그래서 이 노드는 결정적인 문자열 포매팅만 수행하고 LLM을
    호출하지 않는다.
    """
    scope = state.get("retrieval_scope")
    docs = state.get("retrieved_docs", [])

    if scope == "this_patient":
        lines = [f"[오늘 날짜: {date.today().isoformat()}]", "[환자 진단 타임라인]"]
        for d in docs:
            confidence = d.get("confidence_score")
            confidence_text = f"{confidence:.2f}" if confidence is not None else "-"
            lines.append(
                f"- diagnosis_id={d['diagnosis_id']} | {d['date']} | {d['anatomy_site']} | "
                f"{d['diagnosis']}({d.get('diagnosis_detail') or '-'}) | confidence={confidence_text} | "
                f"처방: {d.get('prescription') or '-'} | 환자 반응: {d.get('concern') or '-'}"
            )
    else:
        lines = ["[유사 환자 사례(익명화됨)]"]
        if docs:
            lines.append(
                f"[현재 환자] 나이 {docs[0].get('current_patient_age') or '-'}세 | "
                f"성별 {docs[0].get('current_patient_sex') or '-'}"
            )
        for c in docs:
            lines.append(
                f"- {c['anonymized_label']} | {c['date']} | {c['anatomy_site']} | "
                f"{c['diagnosis']}({c.get('diagnosis_detail') or '-'}) | similarity={c['similarity']:.2f} | "
                f"나이 {c.get('age') or '-'}세 | 성별 {c.get('sex') or '-'} | "
                f"처방: {c.get('prescription') or '-'} | 환자 반응: {c.get('concern') or '-'}"
            )

    if not docs:
        lines.append("(검색 결과 없음)")

    return {"organized_context": "\n".join(lines)}


GENERATE_SYSTEM_PROMPT = (
    "당신은 피부과 의사용 환자 히스토리 브리핑 어시스턴트입니다. 아래 [컨텍스트]에 "
    "근거해서만 답변하고, brief/similar_cases/answer 3개 응답 타입 중 대화 의도에 "
    "가장 맞는 하나를 선택해 구조화된 형식으로 답하세요. 컨텍스트에 없는 사실은 "
    "만들어내지 마세요. 타 환자의 실제 식별정보는 절대 포함하지 말고 익명화 라벨만 "
    "사용하세요. 검색이 수행되지 않은 일반 질문이면 answer_text만으로 답하세요. "
    "timeline/cases의 diagnosis 필드에는 컨텍스트의 '진단(세부라벨)' 표기에서 "
    "괄호 앞의 benign 또는 malignant 값만 넣고, 세부 라벨(예: melanoma, nevus)은 "
    "diagnosis 필드에 포함하지 마세요 — 필요하면 narrative_summary/answer_text 등 "
    "서술형 텍스트에서만 언급하세요.\n"
    "brief 응답을 생성할 때는 다음을 지키세요 — narrative_summary는 방문 간격(예: "
    "'최근 2년간 총 5회 내원, 평균 방문 간격 약 5개월'), 방문별 처방 변화, 환자 "
    "우려점의 변화를 컨텍스트에 있는 구체적인 수치·문구로 서술하세요. '정기적인 "
    "추적 관찰이 필요합니다' 같은 일반론적 문장만으로 narrative_summary나 "
    "recommendation을 채우지 마세요. recommendation은 직전 방문일로부터 오늘까지 "
    "경과한 기간을 계산하고, 통상적인 관찰 주기(양성은 3~6개월, 악성 이력이 있으면 "
    "더 짧게)를 근거로 삼아 다음 진료가 왜 필요한지, 언제쯤이 적절한지를 구체적으로 "
    "제시하세요.\n"
    "similar_cases 응답을 생성할 때는 컨텍스트의 '[현재 환자]' 나이·성별과 각 "
    "사례의 나이·성별을 반드시 비교하세요. shared_features/differences에는 "
    "부위·진단 결과 같은 임상 정보뿐 아니라 나이대·성별의 일치·차이도 구체적으로 "
    "포함하세요(예: '동일 부위(torso)에서 발생'은 shared_features에, "
    "'환자 연령대 차이(60대 vs 40대)'는 differences에). clinical_note은 시스템이 "
    "진단·환자 호소·처방 요약으로 자동으로 덮어쓰므로, 짧은 placeholder 문장만 "
    "채워 두세요 — 이 필드에서는 진행 속도·예후처럼 컨텍스트에 없는 의학적 "
    "인과관계를 절대 단정하지 마세요."
)


def _final_response_text(response) -> str:
    if hasattr(response, "narrative_summary"):
        return response.narrative_summary
    return response.answer_text


def _has_final_consonant(text: str) -> bool:
    """조사(을/를 등) 선택을 위해 마지막 한글 음절에 받침이 있는지 판정한다."""
    for ch in reversed(text.strip()):
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            return (code - 0xAC00) % 28 != 0
        if ch.isalnum():
            return False  # 영문/숫자로 끝나면 받침 없는 것으로 취급
    return False


def _josa_eul_reul(text: str) -> str:
    return "을" if _has_final_consonant(text) else "를"


def _deterministic_case_summary(diagnosis, diagnosis_detail, prescription, concern) -> str:
    """이 사례의 진단·환자 호소·처방을 DB 기록 그대로 조립한 요약 문장을 만든다.

    이전에는 나이·성별 차이 여부만 안내했는데("연령대 차이가 있으니 의사가
    판단해 주세요"), 실제 QA에서 이 문장이 사례 내용을 전혀 설명하지 못해
    쓸모가 없다는 피드백을 받았다. 진단명/환자 호소/처방은 이미 DB에 구조화된
    사실이라 LLM이 요약해도 새로 판단할 게 없고, 오히려 LLM에게 맡기면
    컨텍스트에 없는 인과관계를 덧붙이는 사례가 있었으므로(수동 QA에서 반복
    확인됨) 그대로 문장으로 조립하는 것까지 결정적 로직으로 처리한다.
    """
    label = diagnosis_detail or diagnosis or "질환"
    clauses = [f"{label} 진단을 받았"]
    if concern:
        clauses.append(f"환자가 {concern}{_josa_eul_reul(concern)} 호소했")
    if prescription:
        clauses.append(f"{prescription}{_josa_eul_reul(prescription)} 처방받았")
    return "고, ".join(clauses) + "습니다."


def generate(state: AgentState, config: RunnableConfig) -> dict:
    """organized_context에 근거해 3종 응답 스키마 중 하나로 최종 답변을 생성하는 노드.

    grade_answer의 재시도 지시로도 재진입한다(regenerate_count > 0). 이
    경우 answer_grade_reasoning(직전 평가에서 무엇이 근거 부족이었는지)을
    시스템 메시지로 추가해, 단순히 같은 프롬프트로 다시 시도하는 게 아니라
    구체적인 피드백을 반영해 재생성하도록 한다.
    """
    context_text = state.get("organized_context") or "(검색 결과 없음 — 검색이 필요 없는 일반 질문일 수 있음)"
    messages = [
        SystemMessage(content=GENERATE_SYSTEM_PROMPT),
        *state["messages"],
        SystemMessage(content=f"[컨텍스트]\n{context_text}"),
    ]
    if state.get("regenerate_count", 0) > 0 and state.get("answer_grade_reasoning"):
        messages.append(
            SystemMessage(
                content=(
                    f"[이전 답변 재검토 피드백] {state['answer_grade_reasoning']} "
                    "이 문제를 해결해 컨텍스트에 근거한 답변만 다시 생성하세요."
                )
            )
        )

    envelope: ChatResponseEnvelope = (
        _get_llm().with_structured_output(ChatResponseEnvelope, method="function_calling").invoke(messages)
    )
    response = envelope.response

    if getattr(response, "type", None) == "similar_cases":
        docs_by_label = {d["anonymized_label"]: d for d in state.get("retrieved_docs", [])}
        for case in response.cases:
            doc = docs_by_label.get(case.anonymized_label)
            if doc is not None:
                case.clinical_note = _deterministic_case_summary(
                    doc.get("diagnosis"),
                    doc.get("diagnosis_detail"),
                    doc.get("prescription"),
                    doc.get("concern"),
                )

    return {
        "final_response": response.model_dump(),
        "messages": [AIMessage(content=_final_response_text(response))],
    }


GRADE_ANSWER_SYSTEM_PROMPT = (
    "생성된 답변에 포함된 모든 사실 주장이 [컨텍스트]로 뒷받침되는지 평가하세요. "
    "컨텍스트에 없는 사실을 답변이 만들어냈다면 근거 부족(is_grounded=false)으로 "
    "판단하고, 근거 없는 구체적인 문장을 unsupported_claims에 나열하세요.\n"
    "중요 — 부재(없음) 주장 판정 규칙: [컨텍스트]는 해당 범위에서 확인 가능한 전체 "
    "정보(예: 환자 본인의 전체 진단 이력)입니다. 답변이 '~에 대한 기록이 없다/본 적이 "
    "없다'처럼 특정 항목의 부재를 진술할 경우, 그 항목이 컨텍스트 전체를 뒤져도 전혀 "
    "등장하지 않는다면 이 부재 진술은 grounded로 판정해야 합니다. 컨텍스트에 '없다'는 "
    "문장이 글자 그대로 적혀 있을 것을 요구하지 마세요.\n"
    "예시: 컨텍스트에 'torso 진단 1건, upper_extremity 진단 1건'만 있고 답변이 "
    "'head_neck(두피) 진단 기록은 없습니다'라고 말했다면 → 컨텍스트의 어떤 항목도 "
    "head_neck이 아니므로 이 부재 진술은 grounded(근거 충분)입니다. is_grounded=false로 "
    "판정하면 틀린 것입니다.\n"
    "중요 — 권고(recommendation) 문구 판정 규칙: recommendation 필드는 컨텍스트의 "
    "구체적 사실(진단일, 진단 결과, 오늘 날짜 등)에 기반해 다음 진료 시점을 "
    "'추정·제안'하는 문구입니다. 방문 주기·관찰 기간처럼 일반적인 임상 관행에 대한 "
    "지식을 근거로 특정 날짜/기간을 제안했다면, 그 날짜 자체가 컨텍스트에 글자 그대로 "
    "적혀 있지 않아도 컨텍스트의 사실(진단일, 오늘 날짜, 진단 결과)에서 합리적으로 "
    "도출된 제안이면 grounded로 판정하세요. narrative_summary/timeline/summary처럼 "
    "과거 사실을 서술하는 필드에서 컨텍스트에 없는 사실을 만들어낸 경우에만 근거 "
    "부족으로 판정하세요."
)


def grade_answer(state: AgentState, config: RunnableConfig) -> dict:
    """생성된 답변이 organized_context에 근거하는지 평가하는 할루시네이션 체크 노드.

    grade_documents와 달리 _get_grading_llm()(gpt-4o)을 쓴다 — 이 노드는
    "~에 대한 기록이 없다"류의 부재 진술이 컨텍스트에 근거하는지를 판단해야
    하는데, 부재를 증명하려면 컨텍스트 전체를 훑어 해당 항목이 정말 없는지
    확인하는 한 단계 더 깊은 추론이 필요하다. gpt-4o-mini로는 이런 부재
    진술이나 동의어 표현("상체" vs "torso")을 과도하게 엄격하게 근거
    부족으로 오판하는 사례가 실제 검증 중 확인되어, 가드레일의 최종
    안전판인 이 노드에만 더 큰 모델을 쓴다.
    """
    grade: AnswerGrade = (
        _get_grading_llm()
        .with_structured_output(AnswerGrade, method="function_calling")
        .invoke(
            [
                SystemMessage(content=GRADE_ANSWER_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"컨텍스트:\n{state.get('organized_context') or '(없음)'}\n\n"
                        f"생성된 답변:\n{state.get('final_response')}"
                    )
                ),
            ]
        )
    )

    update: dict = {
        "answer_grounded": grade.is_grounded,
        "answer_grade_reasoning": grade.reasoning,
    }
    if not grade.is_grounded:
        update["regenerate_count"] = state["regenerate_count"] + 1
    return update


def fallback_answer(state: AgentState, config: RunnableConfig) -> dict:
    """재시도 한도를 초과했을 때 안전한 answer 응답으로 강제 전환하는 노드(LLM 미사용, 무한 루프 방지의 최종 안전판).

    이 노드는 grade_documents 루프(문서 불충분) 또는 grade_answer 루프(근거
    부족)의 두 경로 중 하나로 진입할 수 있다. answer_grounded가 False로 명시적
    으로 설정되어 있으면 실제 실패 지점은 grade_answer이므로
    answer_grade_reasoning을 우선 사용한다 — doc_grade_reasoning은 그 경우
    grade_documents가 "충분함"으로 판단했을 때도 항상 채워져 있어(this_patient
    스코프는 결정적으로 항상 채움) 실제 실패 원인을 가리는 문제가 있었다.
    """
    if state.get("answer_grounded") is False and state.get("answer_grade_reasoning"):
        reason = state["answer_grade_reasoning"]
    else:
        reason = (
            state.get("doc_grade_reasoning")
            or state.get("answer_grade_reasoning")
            or "요청을 처리하는 데 필요한 정보를 충분히 확인하지 못했습니다."
        )
    text = f"죄송합니다. 이 질문에 확실하게 답변드리기 어렵습니다. ({reason}) 질문을 조금 더 구체적으로 다시 말씀해 주시겠어요?"
    response = AnswerResponse(answer_text=text, citations=[])

    return {
        "final_response": response.model_dump(),
        "messages": [AIMessage(content=text)],
    }
