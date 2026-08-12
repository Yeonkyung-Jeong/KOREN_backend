# app/agent/routing.py
# add_conditional_edges에 넘기는 라우팅 함수 3개. 순수 read-only 함수로,
# 상태를 바꾸지 않고 다음 노드 이름만 반환한다 — 카운터 증가 등 상태 변경은
# 판단을 내리는 노드 자신(grade_documents/grade_answer)이 담당한다.
from typing import Literal

from langgraph.graph import END

from app.agent.state import MAX_REGENERATIONS, MAX_REWRITES, AgentState


def route_after_route_query(state: AgentState) -> Literal["generate", "rewrite_query", "retrieve"]:
    """route_query 다음 분기: 검색 불필요 → generate, 검색 필요+모호 → rewrite_query, 검색 필요+명확 → retrieve."""
    if not state.get("needs_retrieval", False):
        return "generate"
    if state.get("needs_rewrite", False):
        return "rewrite_query"
    return "retrieve"


def route_after_grade_documents(
    state: AgentState,
) -> Literal["rewrite_query", "fallback_answer", "context_organizer"]:
    """grade_documents 다음 분기: 충분 → context_organizer, 불충분+한도 내 → rewrite_query 루프, 불충분+한도 초과 → fallback_answer."""
    if state.get("doc_grade_sufficient", False):
        return "context_organizer"
    if state.get("rewrite_count", 0) >= MAX_REWRITES:
        return "fallback_answer"
    return "rewrite_query"


def route_after_grade_answer(state: AgentState) -> str:
    """grade_answer 다음 분기: 통과 → END, 근거 부족+한도 내 → generate 루프, 근거 부족+한도 초과 → fallback_answer."""
    if state.get("answer_grounded", False):
        return END
    if state.get("regenerate_count", 0) >= MAX_REGENERATIONS:
        return "fallback_answer"
    return "generate"
