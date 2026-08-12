from langgraph.graph import END

from app.agent.routing import (
    route_after_grade_answer,
    route_after_grade_documents,
    route_after_route_query,
)
from app.agent.state import MAX_REGENERATIONS, MAX_REWRITES


def test_route_after_route_query_no_retrieval_goes_to_generate():
    assert route_after_route_query({"needs_retrieval": False}) == "generate"


def test_route_after_route_query_needs_rewrite():
    state = {"needs_retrieval": True, "needs_rewrite": True}
    assert route_after_route_query(state) == "rewrite_query"


def test_route_after_route_query_clear_query_goes_to_retrieve():
    state = {"needs_retrieval": True, "needs_rewrite": False}
    assert route_after_route_query(state) == "retrieve"


def test_route_after_grade_documents_sufficient_goes_to_context_organizer():
    assert route_after_grade_documents({"doc_grade_sufficient": True}) == "context_organizer"


def test_route_after_grade_documents_insufficient_within_limit_loops_back():
    state = {"doc_grade_sufficient": False, "rewrite_count": MAX_REWRITES - 1}
    assert route_after_grade_documents(state) == "rewrite_query"


def test_route_after_grade_documents_insufficient_over_limit_falls_back():
    state = {"doc_grade_sufficient": False, "rewrite_count": MAX_REWRITES}
    assert route_after_grade_documents(state) == "fallback_answer"


def test_route_after_grade_answer_grounded_ends():
    assert route_after_grade_answer({"answer_grounded": True}) == END


def test_route_after_grade_answer_ungrounded_within_limit_loops_back():
    state = {"answer_grounded": False, "regenerate_count": MAX_REGENERATIONS - 1}
    assert route_after_grade_answer(state) == "generate"


def test_route_after_grade_answer_ungrounded_over_limit_falls_back():
    state = {"answer_grounded": False, "regenerate_count": MAX_REGENERATIONS}
    assert route_after_grade_answer(state) == "fallback_answer"
