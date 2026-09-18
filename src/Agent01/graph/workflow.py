from __future__ import annotations

from langgraph.graph import END, START, StateGraph #导入画图工具包

from Agent01.graph.nodes import actor_node, final_node, planner_node, verifier_node, verifier_route #导入所有节点
from Agent01.graph.state import Agent01GraphState

def build_workflow():
    graph = StateGraph(Agent01GraphState) #创建一个 LangGraph 工作流构建对象，并指定它的共享状态结构为 Agent01GraphState
    graph.add_node("planner", planner_node)
    graph.add_node("actor", actor_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("final", final_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "actor")
    graph.add_edge("actor", "verifier")
    graph.add_conditional_edges("verifier", verifier_route, {"planner": "planner", "final": "final"})
    graph.add_edge("final", END)
    return graph.compile()