import pytest
from pydantic import ValidationError

from app.agent.schemas import (
    AnswerResponse,
    BriefResponse,
    ChatResponseEnvelope,
    RetrievePatientHistoryArgs,
    SimilarCasesResponse,
)


def test_chat_response_envelope_discriminates_brief():
    envelope = ChatResponseEnvelope.model_validate(
        {
            "response": {
                "type": "brief",
                "summary": {"total_diagnoses": 1, "date_range": "2025-01-01 ~ 2025-01-01"},
                "timeline": [
                    {
                        "diagnosis_id": 1,
                        "date": "2025-01-01",
                        "anatomy_site": "torso",
                        "diagnosis": "benign",
                        "confidence_score": 0.5,
                    }
                ],
                "narrative_summary": "요약",
                "recommendation": "권고",
            }
        }
    )
    assert isinstance(envelope.response, BriefResponse)


def test_chat_response_envelope_discriminates_similar_cases():
    envelope = ChatResponseEnvelope.model_validate(
        {
            "response": {
                "type": "similar_cases",
                "cases": [],
                "answer_text": "유사 사례가 없습니다.",
            }
        }
    )
    assert isinstance(envelope.response, SimilarCasesResponse)


def test_chat_response_envelope_discriminates_answer():
    envelope = ChatResponseEnvelope.model_validate(
        {"response": {"type": "answer", "answer_text": "네, 기록이 있습니다."}}
    )
    assert isinstance(envelope.response, AnswerResponse)
    assert envelope.response.citations == []


def test_chat_response_envelope_rejects_unknown_type():
    with pytest.raises(ValidationError):
        ChatResponseEnvelope.model_validate({"response": {"type": "unknown", "answer_text": "x"}})


def test_retrieve_patient_history_args_defaults():
    args = RetrievePatientHistoryArgs(scope="this_patient", query_text="브리핑 해줘")
    assert args.benign_malignant is None
    assert args.top_k == 5
