# app/agent/schemas.py
# 환자 히스토리 브리핑 어시스턴트(LangGraph 에이전틱 RAG)의 구조화 출력/도구 인자 스키마.
# PRD: docs/prd-patient-history-assistant.md §6(응답 3종), §9.2(도구 인자)
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field
from typing_extensions import Annotated

# -----------------------------------------------------------------------------
# 그래프 내부 판단용 구조화 출력 스키마 (route_query / rewrite_query /
# grade_documents / grade_answer 노드에서 llm.with_structured_output()으로 사용)
# -----------------------------------------------------------------------------


class RouteDecision(BaseModel):
    """의사의 최신 메시지에 검색이 필요한지 판단한 결과.

    route_query 노드가 대화 맥락(state.messages) 전체를 보고 생성한다. 검색
    필요 여부를 미리 규칙으로 분기하지 않고 매 턴 LLM이 판단하게 함으로써,
    "브리핑 해줘"류의 명시적 요청뿐 아니라 자연어로 다양하게 표현된 요청도
    유연하게 처리한다.

    Attributes:
        needs_retrieval: 이 메시지에 답하기 위해 환자 진단 이력 또는 유사
            환자 사례 검색이 필요하면 True. 인사말, 이전 답변에 대한 단순
            재확인처럼 이미 오간 대화 맥락만으로 답할 수 있으면 False.
        needs_rewrite: needs_retrieval이 True이면서, 메시지 자체가 너무
            짧거나("비슷한 거 있어?"처럼 대상이 불명확) 모호해 검색 쿼리로
            바로 쓰기 부적합하면 True. needs_retrieval이 False이면 이
            필드는 무시된다.
    """

    needs_retrieval: bool = Field(description="환자 이력/유사 사례 검색이 필요한지 여부")
    needs_rewrite: bool = Field(
        description="검색이 필요하고 메시지가 모호하거나 지나치게 간결해 질의 재작성이 필요한지 여부"
    )


class RewrittenQuery(BaseModel):
    """검색 품질을 높이기 위해 재작성된 질의.

    rewrite_query 노드가 원 메시지의 의도를 유지하면서, 벡터/SQL 검색에
    바로 사용할 수 있도록 구체화한 한국어 질의를 생성한다. scope(어느
    환자를 검색할지)는 이 노드가 아니라 retrieve 노드에서 LLM이
    bind_tools로 직접 채운다.

    Attributes:
        rewritten_query_text: 부위/기간/증상 등 검색 단서를 살려 재작성한
            한국어 질의 문자열. 환자 이름 등 검색과 무관한 정보는 제외한다.
    """

    rewritten_query_text: str = Field(description="검색에 적합하게 재작성된 질의")


class DocumentGrade(BaseModel):
    """retrieve 노드가 가져온 검색 결과의 적합성 평가.

    grade_documents 노드가 질의와 검색 결과를 비교해 생성한다. 결과가
    비어있거나 질의와 무관하면 불충분으로 판단되어 rewrite_query로
    재시도되거나(재시도 한도 이내), 한도를 넘으면 fallback_answer로
    전환된다.

    reasoning을 is_sufficient보다 먼저 선언한 이유: OpenAI 구조화 출력은 필드
    선언 순서대로 값을 채우므로, 판정(is_sufficient)보다 근거(reasoning)를
    먼저 쓰게 하면 모델이 결론부터 정하고 근거를 끼워 맞추는 대신 근거를 먼저
    따져본 뒤 결론을 내리게 된다.

    Attributes:
        reasoning: 판단 근거. 불충분하다고 판단한 경우, rewrite_query
            노드가 다음 재작성에 참고할 수 있도록 구체적으로 작성한다
            (예: "similar_patients 결과가 0건이라 부위 조건을 완화해야 함").
        is_sufficient: 검색 결과가 질의에 답하기에 충분히 관련성 있고
            개수가 확보되어 있으면 True.
    """

    reasoning: str = Field(description="판단 근거, 재시도 시 참고할 구체적인 설명")
    is_sufficient: bool = Field(description="검색 결과가 질의에 답하기에 충분한지 여부")


class AnswerGrade(BaseModel):
    """generate 노드가 만든 답변이 organized_context에 근거하는지 평가.

    grade_answer 노드가 (organized_context, 생성된 답변)을 비교해 생성한다.
    할루시네이션(컨텍스트로 뒷받침되지 않는 사실 주장) 여부를 판별하는
    최종 가드레일이다.

    reasoning을 is_grounded보다 먼저 선언한 이유: OpenAI 구조화 출력은 필드
    선언 순서대로 값을 채우므로, 판정(is_grounded)보다 근거(reasoning)를
    먼저 쓰게 하면 모델이 결론부터 정하고 근거를 끼워 맞추는 대신 근거를 먼저
    따져본 뒤 결론을 내리게 된다.

    Attributes:
        reasoning: 판단 근거. 근거 부족으로 판정한 경우, generate 노드가
            재생성 시 무엇을 고쳐야 하는지 알 수 있도록 구체적으로 작성한다.
        unsupported_claims: 컨텍스트로 뒷받침되지 않는 구체적인 문장/주장
            목록. 근거가 충분하면 빈 리스트.
        is_grounded: 답변에 포함된 모든 사실 주장이 organized_context로
            뒷받침되면 True.
    """

    reasoning: str = Field(description="판단 근거, 재생성 시 참고할 구체적인 설명")
    unsupported_claims: list[str] = Field(
        default_factory=list, description="컨텍스트로 뒷받침되지 않는 주장 목록"
    )
    is_grounded: bool = Field(description="답변이 컨텍스트에 근거하는지 여부")


# -----------------------------------------------------------------------------
# PRD §6: 최종 응답 3종 (generate / fallback_answer 노드의 출력이자
# POST /patients/{patient_id}/chat 응답의 `response` 필드 그대로)
# -----------------------------------------------------------------------------


class TimelineEntry(BaseModel):
    """브리핑 응답에 포함되는 진단 타임라인 항목 1건.

    Attributes:
        diagnosis_id: 해당 진단의 diagnoses.id (내부 PK).
        date: 진단일(YYYY-MM-DD).
        anatomy_site: 병변 부위(head_neck/upper_extremity/lower_extremity/torso).
        diagnosis: 진단 결과(benign/malignant).
        confidence_score: 모델 예측 확신도(0.0~1.0).
    """

    diagnosis_id: int = Field(description="진단 레코드의 내부 PK")
    date: str = Field(description="진단일(YYYY-MM-DD)")
    anatomy_site: str = Field(description="병변 부위")
    diagnosis: str = Field(description="진단 결과(benign/malignant)")
    confidence_score: float = Field(description="모델 예측 확신도")


class BriefSummary(BaseModel):
    """브리핑 응답의 요약 통계.

    Attributes:
        total_diagnoses: 이 환자의 전체 진단 건수.
        date_range: 최초~최근 진단일 범위 문자열(예: "2023-02-10 ~ 2025-11-03").
    """

    total_diagnoses: int = Field(description="전체 진단 건수")
    date_range: str = Field(description="최초~최근 진단일 범위")


class BriefResponse(BaseModel):
    """type: "brief" — 재진 환자의 진단 이력 브리핑 응답(PRD §6.1).

    Attributes:
        type: 응답 타입 판별자. 항상 "brief".
        summary: 전체 진단 건수/기간 요약.
        timeline: diagnosed_at 오름차순으로 정렬된 진단 이력 목록.
        narrative_summary: 방문 간격/처방/환자 반응 변화를 근거로 생성한
            서술형 요약.
        recommendation: 방문 주기 등을 근거로 한 다음 진료 권고 문구.
    """

    type: Literal["brief"] = "brief"
    summary: BriefSummary = Field(description="전체 진단 건수/기간 요약")
    timeline: list[TimelineEntry] = Field(description="diagnosed_at 오름차순 진단 이력")
    narrative_summary: str = Field(description="방문 간격·처방·환자 반응 변화를 근거로 한 서술형 요약")
    recommendation: str = Field(description="다음 진료에 대한 권고 문구")


class SimilarCase(BaseModel):
    """유사 사례 응답에 포함되는 타 환자 사례 1건(익명화됨).

    Attributes:
        anonymized_label: 실제 patient_id 대신 노출하는 익명 라벨
            (예: "유사 사례 A"). 도구 레벨에서부터 실제 식별정보 대신
            이 라벨로 치환되어 반환된다.
        date: 진단일(YYYY-MM-DD).
        anatomy_site: 병변 부위.
        diagnosis: 진단 결과(benign/malignant).
        similarity: 현재 환자 질의와의 코사인 유사도(0.0~1.0).
        shared_features: 현재 환자와 공통되는 특징 목록.
        differences: 현재 환자와 다른 점 목록.
        clinical_note: 차이점을 고려한 임상적 주의사항 한두 문장.
    """

    anonymized_label: str = Field(description="실제 환자 식별정보 대신 노출하는 익명 라벨")
    date: str = Field(description="진단일(YYYY-MM-DD)")
    anatomy_site: str = Field(description="병변 부위")
    diagnosis: str = Field(description="진단 결과(benign/malignant)")
    similarity: float = Field(description="현재 환자 질의와의 코사인 유사도")
    shared_features: list[str] = Field(description="현재 환자와 공통되는 특징")
    differences: list[str] = Field(description="현재 환자와 다른 점")
    clinical_note: str = Field(description="차이점을 고려한 임상적 주의사항")


class SimilarCasesResponse(BaseModel):
    """type: "similar_cases" — 유사 환자 사례 질문 응답(PRD §6.2).

    Attributes:
        type: 응답 타입 판별자. 항상 "similar_cases".
        cases: 익명화된 유사 사례 목록. 실제 patient_id/name은 절대
            포함하지 않는다.
        answer_text: 사례들을 종합한 요약 문장.
    """

    type: Literal["similar_cases"] = "similar_cases"
    cases: list[SimilarCase] = Field(description="익명화된 유사 사례 목록")
    answer_text: str = Field(description="사례들을 종합한 요약 문장")


class Citation(BaseModel):
    """일반 질문 응답의 인용 근거 1건. 이 환자 본인의 기록만 인용 가능.

    Attributes:
        diagnosis_id: 인용한 진단 레코드의 내부 PK.
        date: 진단일(YYYY-MM-DD).
        anatomy_site: 병변 부위.
    """

    diagnosis_id: int = Field(description="인용한 진단 레코드의 내부 PK")
    date: str = Field(description="진단일(YYYY-MM-DD)")
    anatomy_site: str = Field(description="병변 부위")


class AnswerResponse(BaseModel):
    """type: "answer" — 그 외 일반 질문 응답(PRD §6.3). fallback_answer
    노드도 이 스키마를 그대로 사용한다.

    Attributes:
        type: 응답 타입 판별자. 항상 "answer".
        answer_text: 질문에 대한 답변 문장.
        citations: 이 환자 본인의 기록 중 답변 근거가 된 항목 목록. 타
            환자 인용이 필요한 질문은 SimilarCasesResponse로 유도되므로
            여기 포함되지 않는다.
    """

    type: Literal["answer"] = "answer"
    answer_text: str = Field(description="질문에 대한 답변 문장")
    citations: list[Citation] = Field(default_factory=list, description="답변 근거가 된 이 환자 기록 목록")


ChatResponse = Annotated[
    Union[BriefResponse, SimilarCasesResponse, AnswerResponse],
    Field(discriminator="type"),
]


class ChatResponseEnvelope(BaseModel):
    """generate 노드가 llm.with_structured_output()에 사용하는 envelope.

    OpenAI 구조화 출력 호환성을 위해 discriminated union(ChatResponse)을
    단일 필드로 감싼다. API 응답의 `response` 필드에는 이 envelope의
    response 값만 그대로 사용된다.

    Attributes:
        response: brief/similar_cases/answer 3종 중 대화 의도에 맞는 하나.
    """

    response: ChatResponse = Field(description="brief/similar_cases/answer 3종 중 하나")


# -----------------------------------------------------------------------------
# PRD §9.2: retrieve_patient_history 도구 인자 스키마
# -----------------------------------------------------------------------------


class RetrievePatientHistoryArgs(BaseModel):
    """retrieve_patient_history 도구의 호출 인자.

    retrieve 노드가 llm.bind_tools()로 이 스키마를 바인딩하고, LLM이
    scope/query_text/benign_malignant/top_k를 스스로 채운다. 실제
    조회 대상 환자(patient_id)는 이 스키마에 포함하지 않고
    RunnableConfig를 통해 도구 구현부에 주입한다 — LLM이 임의의 다른
    환자를 조회하는 경로 자체를 차단하기 위함(PRD §9.2).

    Attributes:
        scope: "this_patient"면 현재 환자 본인의 진단 이력을 SQL
            필터+시간순 정렬로 조회(브리핑, 특정 이력 질문용).
            "similar_patients"면 diagnosis(benign/malignant) 1차
            필터 후 벡터 코사인 유사도로 정렬한 타 환자 익명 사례를
            조회.
        query_text: 검색 의도를 담은 자연어 질의. similar_patients
            스코프에서 임베딩 생성에 사용된다.
        benign_malignant: similar_patients 스코프에서 사용하는 1차
            필터 값. 지정하지 않으면 현재 환자의 최신 진단 결과를
            기본값으로 사용한다. this_patient 스코프에서는 무시된다.
        top_k: 반환할 최대 결과 개수.
    """

    scope: Literal["this_patient", "similar_patients"] = Field(description="검색 범위")
    query_text: str = Field(description="검색 의도를 담은 자연어 질의")
    benign_malignant: Optional[Literal["benign", "malignant"]] = Field(
        default=None,
        description="similar_patients 스코프의 1차 필터. 미지정 시 현재 환자의 최신 진단값을 기본으로 사용",
    )
    top_k: int = Field(default=5, description="반환할 최대 결과 개수")
