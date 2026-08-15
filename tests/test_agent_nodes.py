from datetime import date

from app.agent.nodes import _deterministic_case_summary, context_organizer, fallback_answer


def test_context_organizer_formats_this_patient_timeline():
    state = {
        "retrieval_scope": "this_patient",
        "retrieved_docs": [
            {
                "diagnosis_id": 1,
                "date": "2025-01-01",
                "anatomy_site": "torso",
                "diagnosis": "benign",
                "diagnosis_detail": "nevus",
                "confidence_score": 0.12,
                "prescription": "경과 관찰",
                "concern": "특이 증상 없음",
            }
        ],
    }
    result = context_organizer(state, {})
    context = result["organized_context"]
    assert "[환자 진단 타임라인]" in context
    assert "diagnosis_id=1" in context
    assert "confidence=0.12" in context
    assert "경과 관찰" in context


def test_context_organizer_injects_todays_date_for_this_patient_scope():
    state = {
        "retrieval_scope": "this_patient",
        "retrieved_docs": [
            {
                "diagnosis_id": 1,
                "date": "2025-01-01",
                "anatomy_site": "torso",
                "diagnosis": "benign",
                "diagnosis_detail": "nevus",
                "confidence_score": 0.12,
                "prescription": "경과 관찰",
                "concern": "특이 증상 없음",
            }
        ],
    }
    result = context_organizer(state, {})
    assert f"[오늘 날짜: {date.today().isoformat()}]" in result["organized_context"]


def test_context_organizer_formats_similar_patients_cases():
    state = {
        "retrieval_scope": "similar_patients",
        "retrieved_docs": [
            {
                "anonymized_label": "유사 사례 A",
                "date": "2024-06-12",
                "anatomy_site": "torso",
                "diagnosis": "malignant",
                "diagnosis_detail": None,
                "similarity": 0.874,
            }
        ],
    }
    result = context_organizer(state, {})
    context = result["organized_context"]
    assert "[유사 환자 사례(익명화됨)]" in context
    assert "유사 사례 A" in context
    assert "similarity=0.87" in context


def test_context_organizer_handles_empty_results():
    state = {"retrieval_scope": "this_patient", "retrieved_docs": []}
    result = context_organizer(state, {})
    assert "검색 결과 없음" in result["organized_context"]
    assert f"[오늘 날짜: {date.today().isoformat()}]" in result["organized_context"]


def test_fallback_answer_produces_valid_answer_response():
    state = {"doc_grade_reasoning": "검색 결과가 0건입니다."}
    result = fallback_answer(state, {})
    assert result["final_response"]["type"] == "answer"
    assert "검색 결과가 0건입니다." in result["final_response"]["answer_text"]
    assert result["messages"][0].content == result["final_response"]["answer_text"]


def test_deterministic_case_summary_includes_diagnosis_concern_prescription():
    note = _deterministic_case_summary(
        "malignant", "melanoma", "광범위 절제술 시행", "전이 여부에 대한 불안"
    )
    assert note.startswith("melanoma 진단을 받았고")
    assert "전이 여부에 대한 불안을 호소했고" in note
    assert "광범위 절제술 시행을 처방받았습니다" in note
    assert "진행" not in note  # 의학적 인과관계(진행 속도 등) 단정 금지
    assert "예후" not in note


def test_deterministic_case_summary_falls_back_to_diagnosis_when_no_detail():
    note = _deterministic_case_summary("benign", None, "경과 관찰", "특이 증상 없음")
    assert note.startswith("benign 진단을 받았고")


def test_deterministic_case_summary_handles_missing_concern_or_prescription():
    note = _deterministic_case_summary("malignant", "melanoma", None, None)
    assert note == "melanoma 진단을 받았습니다."


def test_deterministic_case_summary_picks_batchim_aware_particle():
    # "행"(받침 ㅇ 있음) -> 을, "소"(받침 없음) -> 를
    with_final = _deterministic_case_summary("malignant", "melanoma", "즉시 조직검사 의뢰, 응급 전원 시행", None)
    assert "시행을 처방받았습니다" in with_final

    without_final = _deterministic_case_summary("malignant", "melanoma", None, "회복 여부에 대한 불안 호소")
    assert "불안 호소를 호소했습니다" in without_final


def test_fallback_answer_prefers_answer_grade_reasoning_when_grounding_failed():
    # doc_grade_reasoning은 this_patient 스코프에서 grade_documents가 성공했을 때도
    # 항상 채워지므로, answer_grounded=False(grade_answer 루프에서 온 실패)일 때는
    # 진짜 실패 원인인 answer_grade_reasoning을 우선해야 한다.
    state = {
        "doc_grade_reasoning": "환자 본인의 전체 진단 이력을 확보함.",
        "answer_grounded": False,
        "answer_grade_reasoning": "clinical_note의 예후 판단이 컨텍스트로 뒷받침되지 않습니다.",
    }
    result = fallback_answer(state, {})
    assert "clinical_note의 예후 판단이 컨텍스트로 뒷받침되지 않습니다." in result["final_response"]["answer_text"]
    assert "환자 본인의 전체 진단 이력을 확보함." not in result["final_response"]["answer_text"]
