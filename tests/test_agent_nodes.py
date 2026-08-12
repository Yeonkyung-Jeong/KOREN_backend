from app.agent.nodes import context_organizer, fallback_answer


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


def test_fallback_answer_produces_valid_answer_response():
    state = {"doc_grade_reasoning": "검색 결과가 0건입니다."}
    result = fallback_answer(state, {})
    assert result["final_response"]["type"] == "answer"
    assert "검색 결과가 0건입니다." in result["final_response"]["answer_text"]
    assert result["messages"][0].content == result["final_response"]["answer_text"]
