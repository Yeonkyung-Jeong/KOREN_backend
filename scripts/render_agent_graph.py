# scripts/render_agent_graph.py
# app/agent/graph.py의 컴파일된 StateGraph를 mermaid PNG로 저장한다(요구사항 15).
# draw_mermaid_png() 기본 동작은 mermaid.ink 공개 API를 호출하므로 인터넷 연결이 필요하다.
import sys

sys.path.insert(0, ".")

from app.agent.graph import graph

OUTPUT_PATH = "docs/agent_graph.png"


def render():
    png_bytes = graph.get_graph().draw_mermaid_png()
    with open(OUTPUT_PATH, "wb") as f:
        f.write(png_bytes)
    print(f"[render_agent_graph] 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    render()
