from scripts.embed_diagnoses import build_embedding_text


def test_build_embedding_text_matches_prd_format():
    text = build_embedding_text(
        anatomy_site="torso",
        diagnosis="malignant",
        diagnosis_detail="melanoma",
        confidence_score=0.876,
        prescription="조직검사 의뢰",
        concern="불안 호소",
    )
    assert text == (
        "torso 부위, malignant(melanoma) 소견, confidence 0.88. "
        "처방: 조직검사 의뢰. 환자 반응: 불안 호소."
    )


def test_build_embedding_text_handles_missing_summary():
    text = build_embedding_text(
        anatomy_site="head_neck",
        diagnosis="benign",
        diagnosis_detail="nevus",
        confidence_score=0.12,
        prescription=None,
        concern=None,
    )
    assert "처방: . 환자 반응: ." in text


def test_build_embedding_text_handles_missing_detail_and_score():
    text = build_embedding_text(
        anatomy_site="upper_extremity",
        diagnosis="benign",
        diagnosis_detail=None,
        confidence_score=None,
        prescription="",
        concern="",
    )
    assert "benign()" in text
    assert "confidence 0.00" in text
