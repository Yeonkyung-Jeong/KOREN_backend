# app/agent/state.py
# LangGraph StateGraph의 상태 정의. PostgresSaver로 체크포인트되므로 여기 담기는
# 값은 모두 msgpack 직렬화 가능해야 한다 — DB 세션 등 비직렬화 객체는 절대 넣지
# 말고 RunnableConfig(configurable)로만 전달한다.
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict

# 재작성/재생성 루프 무한 반복 방지 한도 (PRD §9.3 "예: 2회"에 대응)
MAX_REWRITES = 2
MAX_REGENERATIONS = 2


class AgentState(TypedDict):
    """환자 히스토리 브리핑 어시스턴트 그래프의 전체 상태.

    turn마다 채워지는 필드(needs_retrieval 이하)는 매 invoke 시점에
    새로 초기화되어야 한다 — 이전 턴의 재시도 카운트/검색 결과가 다음
    턴으로 새어 들어가지 않도록, 라우터(app/routers/chat.py)가 매 요청마다
    rewrite_count/regenerate_count를 0으로, query_text를 최신 메시지로
    다시 세팅해 invoke한다.

    Attributes:
        messages: 대화 이력. add_messages 리듀서로 누적되며
            PostgresSaver 체크포인터를 통해 thread_id(session_id)별로
            멀티턴 유지된다.
        patient_id: 세션이 종속된 환자의 비즈니스 키(patients.patient_id).
        patient_pk: 세션이 종속된 환자의 내부 PK(patients.id). DB
            조회에 사용되며 LLM에는 노출되지 않는다.
        query_text: 현재 턴에서 검색에 사용할 질의. 최초에는 사용자
            메시지 원문, rewrite_query 노드를 거치면 재작성된 문장으로
            갱신된다.
        needs_retrieval: route_query 노드의 판단 결과.
        needs_rewrite: route_query 노드의 판단 결과.
        rewrite_count: rewrite_query 노드가 실행된 횟수(이번 턴 기준).
            MAX_REWRITES 이상이면 grade_documents가 fallback_answer로
            강제 전환한다.
        regenerate_count: generate 노드가 grade_answer의 재시도 지시로
            다시 실행된 횟수(이번 턴 기준). MAX_REGENERATIONS 이상이면
            grade_answer가 fallback_answer로 강제 전환한다.
        retrieved_docs: retrieve 노드가 도구 호출로 가져온 원시 결과
            목록(this_patient 타임라인 또는 similar_patients 익명 사례).
        retrieval_scope: retrieve 노드가 실제로 호출한 scope
            ("this_patient" | "similar_patients"). context_organizer가
            포맷을 결정하는 데 사용한다.
        doc_grade_sufficient: grade_documents 노드의 판단 결과.
        doc_grade_reasoning: grade_documents 노드의 판단 근거. 루프백 시
            rewrite_query가 재작성 방향을 잡는 데 참고한다.
        organized_context: context_organizer 노드가 retrieved_docs를
            정리한 문자열. generate 노드의 근거 컨텍스트로 사용된다.
        final_response: generate 또는 fallback_answer 노드가 만든 최종
            응답(BriefResponse/SimilarCasesResponse/AnswerResponse 중
            하나를 dict로 직렬화한 값).
        answer_grounded: grade_answer 노드의 판단 결과.
        answer_grade_reasoning: grade_answer 노드의 판단 근거. 루프백 시
            generate가 무엇을 고쳐야 하는지 참고한다.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    patient_id: str
    patient_pk: int
    query_text: str
    needs_retrieval: NotRequired[bool]
    needs_rewrite: NotRequired[bool]
    rewrite_count: int
    regenerate_count: int
    retrieved_docs: NotRequired[list[dict]]
    retrieval_scope: NotRequired[str]
    doc_grade_sufficient: NotRequired[bool]
    doc_grade_reasoning: NotRequired[str]
    organized_context: NotRequired[str]
    final_response: NotRequired[dict]
    answer_grounded: NotRequired[bool]
    answer_grade_reasoning: NotRequired[str]
