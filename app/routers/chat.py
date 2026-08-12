# app/routers/chat.py
# POST /patients/{patient_id}/chat — PRD §5.
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.agent.checkpointer import get_checkpointer
from app.agent.graph import build_production_graph
from app.database import get_db_quiet

router = APIRouter()

_graph = None


def _get_graph():
    # 모듈 임포트 시점이 아니라 최초 요청 시점에 생성 — OPENAI_API_KEY/DATABASE_URL이
    # 없어도 이 모듈을 임포트할 수 있게 하기 위함(테스트 등).
    global _graph
    if _graph is None:
        _graph = build_production_graph()
    return _graph


class ChatRequest(BaseModel):
    message: str = Field(description="의사의 자연어 메시지. 공백/빈 문자열 불가")
    session_id: Optional[str] = Field(
        default=None, description="최초 요청 시 생략(또는 null). 이후 요청부터 첫 응답에서 받은 값을 그대로 포함"
    )


@router.post("/patients/{patient_id}/chat")
def chat(patient_id: str, body: ChatRequest, db: Session = Depends(get_db_quiet)):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is empty")

    patient = db.query(models.Patient).filter(models.Patient.patient_id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if body.session_id:
        session_id = body.session_id
        if not session_id.startswith(f"{patient_id}:"):
            raise HTTPException(status_code=404, detail="Session not found or expired")
        existing = get_checkpointer().get_tuple({"configurable": {"thread_id": session_id}})
        if existing is None:
            raise HTTPException(status_code=404, detail="Session not found or expired")
    else:
        session_id = f"{patient_id}:{uuid.uuid4().hex}"

    initial_state = {
        "messages": [HumanMessage(content=message)],
        "patient_id": patient.patient_id,
        "patient_pk": patient.id,
        "query_text": message,
        "rewrite_count": 0,
        "regenerate_count": 0,
    }
    invoke_config = {
        "configurable": {
            "thread_id": session_id,
            "patient_pk": patient.id,
            "db_session": db,
        }
    }

    try:
        result = _get_graph().invoke(initial_state, config=invoke_config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    final_response = result.get("final_response")
    if not final_response:
        raise HTTPException(status_code=502, detail="Failed to generate structured response")

    return {"session_id": session_id, "response": final_response}
