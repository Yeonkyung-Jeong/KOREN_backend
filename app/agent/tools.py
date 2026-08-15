# app/agent/tools.py
# retrieve 노드가 llm.bind_tools()로 바인딩하는 유일한 검색 도구.
# PRD §9.2, §7.4.
import os
from functools import lru_cache
from typing import Literal, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings

from app import models
from app.agent.schemas import RetrievePatientHistoryArgs

# scripts/embed_diagnoses.py가 diagnoses.embedding을 채울 때 쓴 모델과 반드시
# 같아야 한다 — 임베딩 모델이 다르면 벡터 공간이 달라져 코사인 유사도 비교 자체가
# 무의미해진다.
EMBEDDING_MODEL = "text-embedding-3-small"

# similar_patients 결과에서 실제 patient_id 대신 노출하는 익명 라벨.
_ANONYMIZED_LABEL_LETTERS = "ABC"

# similar_patients 스코프가 반환할 최대 결과 개수. LLM이 매 질의마다 다르게
# 정하게 두면(예: 1개, 5개 제각각) 화면에 노출되는 사례 개수가 일관되지 않고
# 근거도 불명확해지므로, 코드에서 고정값으로 못박는다(PRD 논의 반영).
TOP_K_SIMILAR_CASES = 3


@lru_cache
def _get_embeddings() -> OpenAIEmbeddings:
    # 모듈 임포트 시점이 아니라 최초 호출 시점에 생성한다 — OPENAI_API_KEY가
    # 없어도(예: 순수 로직만 테스트) 이 모듈을 임포트할 수 있게 하기 위함.
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=os.getenv("OPENAI_API_KEY"))


def _anonymized_label(index: int) -> str:
    """검색 결과 순번(0-based)을 익명 라벨 문자열로 변환한다."""
    if index < len(_ANONYMIZED_LABEL_LETTERS):
        return f"유사 사례 {_ANONYMIZED_LABEL_LETTERS[index]}"
    return f"유사 사례 {index + 1}"


def _diagnosis_to_history_dict(diagnosis: "models.Diagnosis") -> dict:
    """scope="this_patient" 결과 1건을 dict로 직렬화한다.

    communication_summary는 diagnosis_id FK로 확정적으로 연결되어 있으므로
    (app/routers/core.py의 /summarize 참고), 시간 근접성 추정 없이 그대로
    조인해서 처방/환자우려점을 채운다. 아직 대화 요약이 없는 진단은 두
    필드가 None이 된다.
    """
    summary = diagnosis.communication_summary
    return {
        "diagnosis_id": diagnosis.id,
        "date": diagnosis.diagnosed_at.date().isoformat() if diagnosis.diagnosed_at else None,
        "anatomy_site": diagnosis.anatomy_site.value if diagnosis.anatomy_site else None,
        "diagnosis": diagnosis.diagnosis.value if diagnosis.diagnosis else None,
        "diagnosis_detail": diagnosis.diagnosis_detail,
        "confidence_score": diagnosis.confidence_score,
        "prescription": summary.처방 if summary else None,
        "concern": summary.환자우려점 if summary else None,
    }


def _retrieve_this_patient(db, patient_pk: int) -> list[dict]:
    """현재 환자의 전체 진단 이력을 diagnosed_at 오름차순으로 반환한다.

    query_text는 의도적으로 받지 않는다 — 이 스코프는 벡터 검색이 아니라
    "환자 본인의 전체 기록"이라는 확정적 SQL 조회이므로, 어떤 질의로
    호출되든 결과는 항상 동일하다. "특정 부위 기록이 없다"는 답변도 이
    전체 이력에서 generate 노드가 스스로 도출해야 하는 사실이다.
    """
    diagnoses = (
        db.query(models.Diagnosis)
        .filter(models.Diagnosis.patient_id == patient_pk)
        .order_by(models.Diagnosis.diagnosed_at.asc())
        .all()
    )
    return [_diagnosis_to_history_dict(d) for d in diagnoses]


def _resolve_default_benign_malignant(db, patient_pk: int) -> Optional[str]:
    """benign_malignant 인자가 생략됐을 때 쓸 기본 필터 값을 현재 환자의 최신 진단에서 가져온다."""
    latest = (
        db.query(models.Diagnosis)
        .filter(models.Diagnosis.patient_id == patient_pk)
        .order_by(models.Diagnosis.diagnosed_at.desc(), models.Diagnosis.id.desc())
        .first()
    )
    return latest.diagnosis.value if latest and latest.diagnosis else None


def _retrieve_similar_patients(
    db,
    patient_pk: int,
    query_text: str,
    benign_malignant: Optional[str],
    anatomy_site: Optional[str],
) -> list[dict]:
    """diagnosis(benign/malignant)·anatomy_site 1차 필터 후 pgvector 코사인 유사도로 정렬된 타 환자 사례를 반환한다(PRD §7.4).

    diagnosis_detail(melanoma/nevus/unknown 등 세분류)이 아니라 diagnosis
    (benign/malignant)로 1차 필터링하는 이유는, mock 데이터의 세분류가
    unknown 비중이 높아 신뢰도가 낮기 때문이다 — 굵은 카테고리로 먼저 걸러
    벡터 유사도 정렬의 입력 후보군을 의미 있게 좁힌다. benign_malignant가
    None으로 확정되지 않으면(예: 현재 환자에게 진단 이력 자체가 없음) 빈
    리스트를 반환한다 — 필터 없이 전체를 검색하면 무관한 사례까지 섞여
    유사도 정렬의 의미가 없어지기 때문이다.

    anatomy_site는 질의가 특정 부위를 명시할 때만 retrieve 노드가 채운다.
    임베딩 텍스트에는 부위가 영문 enum 값(lower_extremity 등)으로 들어가
    있는데, "하지"처럼 한국어 부위 표현의 임베딩이 그 영문 값과 항상
    가깝게 매칭된다는 보장이 없어(실측 결과 "하지" 질의가 upper_extremity
    사례를 더 높은 유사도로 올리는 경우가 있었다), 벡터 유사도만으로는
    부위 지정 질의를 안정적으로 걸러낼 수 없다. 부위가 명시됐을 때는
    이 필터로 결정적으로 좁힌다.

    유사도 기준(쿼리 벡터): 의사가 타이핑한 자유 텍스트(query_text)가 아니라
    "현재 환자 본인의 (필터에 해당하는) 최신 진단 기록"의 임베딩 벡터를 쿼리로
    쓴다. 처음엔 query_text를 임베딩해서 비교했는데, 실측해보니 "이 환자와
    유사사례 줘" 같은 짧고 일반적인 문장은 그 자체의 임베딩이 후보 진단
    기록들과 우연히 가까운지 여부로 순위가 갈려서, 실제로 처방·환자 반응까지
    현재 환자와 거의 동일한 사례조차 하위로 밀려나는 문제가 있었다(수동 QA로
    확인). "이 환자와 비슷한 사례"의 기준은 의사의 질문 문장이 아니라 현재
    환자 본인의 임상 기록이어야 더 타당하므로, 현재 환자의 최신 진단
    임베딩(이미 계산되어 있음)을 그대로 쿼리 벡터로 재사용한다. 현재 환자에게
    (필터와 일치하는) 임베딩된 진단이 아직 없는 예외적인 경우에만 query_text
    임베딩으로 폴백한다.
    """
    if benign_malignant is None:
        benign_malignant = _resolve_default_benign_malignant(db, patient_pk)
    if benign_malignant is None:
        return []

    current_patient = db.query(models.Patient).filter(models.Patient.id == patient_pk).first()
    current_age = current_patient.age if current_patient else None
    current_sex = current_patient.sex.value if current_patient and current_patient.sex else None

    reference_query = (
        db.query(models.Diagnosis)
        .filter(models.Diagnosis.patient_id == patient_pk)
        .filter(models.Diagnosis.diagnosis == benign_malignant)
        .filter(models.Diagnosis.embedding.isnot(None))
    )
    if anatomy_site is not None:
        reference_query = reference_query.filter(models.Diagnosis.anatomy_site == anatomy_site)
    reference_diagnosis = reference_query.order_by(
        models.Diagnosis.diagnosed_at.desc(), models.Diagnosis.id.desc()
    ).first()

    query_vector = (
        reference_diagnosis.embedding
        if reference_diagnosis is not None
        else _get_embeddings().embed_query(query_text)
    )
    distance = models.Diagnosis.embedding.cosine_distance(query_vector)

    query = (
        db.query(models.Diagnosis, (1 - distance).label("similarity"))
        .join(models.Patient, models.Diagnosis.patient_id == models.Patient.id)
        .filter(models.Diagnosis.diagnosis == benign_malignant)
        .filter(models.Diagnosis.patient_id != patient_pk)
        .filter(models.Diagnosis.embedding.isnot(None))
    )
    if anatomy_site is not None:
        query = query.filter(models.Diagnosis.anatomy_site == anatomy_site)

    rows = query.order_by(distance.asc()).limit(TOP_K_SIMILAR_CASES).all()

    results = []
    for index, (diagnosis, similarity) in enumerate(rows):
        summary = diagnosis.communication_summary
        results.append(
            {
                "anonymized_label": _anonymized_label(index),
                "date": diagnosis.diagnosed_at.date().isoformat() if diagnosis.diagnosed_at else None,
                "anatomy_site": diagnosis.anatomy_site.value if diagnosis.anatomy_site else None,
                "diagnosis": diagnosis.diagnosis.value if diagnosis.diagnosis else None,
                "diagnosis_detail": diagnosis.diagnosis_detail,
                "confidence_score": diagnosis.confidence_score,
                "similarity": round(float(similarity), 4),
                "age": diagnosis.patient.age if diagnosis.patient else None,
                "sex": diagnosis.patient.sex.value if diagnosis.patient and diagnosis.patient.sex else None,
                "current_patient_age": current_age,
                "current_patient_sex": current_sex,
                "prescription": summary.처방 if summary else None,
                "concern": summary.환자우려점 if summary else None,
            }
        )
    return results


@tool(args_schema=RetrievePatientHistoryArgs)
def retrieve_patient_history(
    scope: Literal["this_patient", "similar_patients"],
    query_text: str,
    benign_malignant: Optional[Literal["benign", "malignant"]] = None,
    anatomy_site: Optional[Literal["head_neck", "upper_extremity", "lower_extremity", "torso"]] = None,
    *,
    config: RunnableConfig,
) -> list[dict]:
    """환자 본인의 진단 이력을 조회하거나, 익명화된 타 환자 유사 사례를 검색한다.

    scope="this_patient"는 벡터 검색이 아니라 현재 환자로 단순 필터링 후
    diagnosed_at 오름차순 정렬(전체 이력 브리핑에는 유사도 랭킹이
    불필요하므로)하며, communication_summary(처방/환자우려점)도 함께
    반환한다. scope="similar_patients"는 diagnosis(benign/malignant)
    1차 필터 후 pgvector 코사인 유사도로 정렬하고, 현재 환자를 제외하며,
    반환값에는 실제 patient_id 대신 anonymized_label만 포함한다 — 에이전트가
    실수로 타 환자 식별정보를 응답에 포함시키는 것을 도구 레벨에서 차단한다.
    반환 개수는 TOP_K_SIMILAR_CASES로 고정되어 있고 LLM이 바꿀 수 없다 —
    질의마다 개수가 제각각이면 "왜 이 개수인지" 근거가 불명확해지기 때문이다.

    현재 세션의 환자(patient_pk)는 인자가 아니라 config를 통해 주입되므로
    LLM이 다른 환자를 임의로 조회할 수 없다.
    """
    db = config["configurable"]["db_session"]
    patient_pk = config["configurable"]["patient_pk"]

    if scope == "this_patient":
        return _retrieve_this_patient(db, patient_pk)
    return _retrieve_similar_patients(db, patient_pk, query_text, benign_malignant, anatomy_site)
