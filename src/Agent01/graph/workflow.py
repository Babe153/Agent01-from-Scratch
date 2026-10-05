from __future__ import annotations

from langgraph.graph import END, START, StateGraph #导入画图工具包

from Agent01.graph.nodes import (    #导入所有节点
    chat_responder_node,
    intent_router_node,
    intent_route_fn,
    context_compressor_node,
    context_compressor_route,
    context_monitor_node,
    context_monitor_route,
    final_node,
    planner_node,
    verifier_node,
)
from Agent01.graph.state import Agent01GraphState


def build_workflow():
    #保留旧入口供现有调用方使用，仍然返回复杂任务图。
    return build_complex_workflow()


def build_complex_workflow():
    graph = StateGraph(Agent01GraphState) #创建一个 LangGraph 工作流构建对象，并指定它的共享状态结构为 Agent01GraphState
    graph.add_node("planner", planner_node)
    graph.add_node("context_monitor", context_monitor_node)
    graph.add_node("context_compressor", context_compressor_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("final", final_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "context_monitor")
    graph.add_conditional_edges(
        "context_monitor",
        context_monitor_route,
        {"context_compressor": "context_compressor", "verifier": "verifier", "planner": "planner", "final": "final"},
    )
    graph.add_conditional_edges(
        "context_compressor",
        context_compressor_route,
        {"verifier": "verifier", "planner": "planner", "final": "final"},
    )
    graph.add_edge("verifier", "context_monitor")
    graph.add_edge("final", END)
    return graph.compile()


def build_entry_workflow():
    #独立入口图不需要 runtime；workflow 分支到 END 后交回 core/agent.py。
    graph = StateGraph(Agent01GraphState)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("chat_responder", chat_responder_node)

    graph.add_edge(START, "intent_router")
    graph.add_conditional_edges(
        "intent_router",
        intent_route_fn,
        {"chat_responder": "chat_responder", "planner": END},
    )
    graph.add_edge("chat_responder", END)
    return graph.compile()
