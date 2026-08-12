# app/agent/graph.py
# StateGraph 조립. 노드/조건부 엣지 흐름은 docs/prd-patient-history-assistant.md
# §9.3 설계 승인본(대화에서 확정된 그래프 구성) 그대로.
from langgraph.graph import END, StateGraph

from app.agent import nodes, routing
from app.agent.state import AgentState


def build_graph(checkpointer=None):
    """AgentState 기반 StateGraph를 조립해 compile한다.

    Args:
        checkpointer: 멀티턴 대화 유지를 위한 체크포인터. None이면 체크포인트
            없이(단발 실행) compile된다 — LangGraph Studio(`langgraph dev`)는
            커스텀 체크포인터를 무시하고 자체 인메모리 저장소로 감싸 실행하므로,
            Studio용 그래프는 None으로 둔다.
    """
    builder = StateGraph(AgentState)

    builder.add_node("route_query", nodes.route_query)
    builder.add_node("rewrite_query", nodes.rewrite_query)
    builder.add_node("retrieve", nodes.retrieve)
    builder.add_node("grade_documents", nodes.grade_documents)
    builder.add_node("context_organizer", nodes.context_organizer)
    builder.add_node("generate", nodes.generate)
    builder.add_node("grade_answer", nodes.grade_answer)
    builder.add_node("fallback_answer", nodes.fallback_answer)

    builder.set_entry_point("route_query")

    builder.add_conditional_edges(
        "route_query",
        routing.route_after_route_query,
        {"generate": "generate", "rewrite_query": "rewrite_query", "retrieve": "retrieve"},
    )
    builder.add_edge("rewrite_query", "retrieve")
    builder.add_edge("retrieve", "grade_documents")
    builder.add_conditional_edges(
        "grade_documents",
        routing.route_after_grade_documents,
        {
            "rewrite_query": "rewrite_query",
            "fallback_answer": "fallback_answer",
            "context_organizer": "context_organizer",
        },
    )
    builder.add_edge("context_organizer", "generate")
    builder.add_edge("generate", "grade_answer")
    builder.add_conditional_edges(
        "grade_answer",
        routing.route_after_grade_answer,
        {"generate": "generate", "fallback_answer": "fallback_answer", END: END},
    )
    builder.add_edge("fallback_answer", END)

    return builder.compile(checkpointer=checkpointer)


def build_production_graph():
    """FastAPI 런타임에서 사용하는, PostgresSaver가 연결된 그래프(멀티턴 유지)."""
    from app.agent.checkpointer import get_checkpointer

    return build_graph(checkpointer=get_checkpointer())


# LangGraph Studio(langgraph.json)가 임포트하는 모듈 레벨 export.
graph = build_graph()
