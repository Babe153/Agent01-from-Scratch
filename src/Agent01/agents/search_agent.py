from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from Agent01.graph.state import Agent01GraphState #运行状态
from Agent01.prompts.version3 import SEARCH_AGENT_PROMPT #提示词
from Agent01.providers.openai_provider import create_model #创建模型方法
from Agent01.tools.web_search_tool import build_web_search_tool #引入专用工具

Writer = Callable[[dict[str, Any]], None] #给“接收一个字典、返回 None 的函数类型”起一个名字，叫 Writer 只要这个函数符合这个wirter的要求 就可以用这个writer接收
#项目采用这种写法，是为了让搜索 Agent 不用关心事件最终怎么展示。 外层负责选择处理函数，搜索 Agent 只负责在合适的时候调用它

def run_search_agent(
    state: Agent01GraphState,
    instruction: str,
    *,
    writer: Writer | None = None, #这里其实会用writer接收print_event的函数 来打印出信息
    max_loops: int = 4,
) -> dict[str, Any]:
    writer = writer or (lambda _: None)
    model = create_model()
    search_agent = model.bind_tools([build_web_search_tool()])
    messages = [
        SystemMessage(content=SEARCH_AGENT_PROMPT),
        HumanMessage(
            content=(
                f"Task: {state['task']}\n\n"
                f"Planner instruction:\n{instruction}\n\n"
                f"Existing research notes:\n{state.get('research_notes', '')}\n\n"
                "Search as needed and finish with a concise research summary plus source URLs."
            )
        ),
    ]

    produced_messages: list[Any] = []
    queries: list[str] = []
    sources: list[dict[str, Any]] = []
    answers: list[str] = []
    tool_events: list[dict[str, Any]] = []

    for _ in range(max_loops): #这里不需要用到轮次数字，所以变量名写成 _
        response = search_agent.invoke(messages)
        produced_messages.append(response)
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            args = call.get("args") or {}
            query = str(args.get("query", ""))
            if query:
                queries.append(query)
            writer({"type": "tool_call", "node": "searchAgent", "name": call.get("name"), "args": args})
            tool_result = _execute_search_tool(call)
            event = _tool_result_event(tool_result)
            tool_events.append(event)
            writer(event)
            parsed = _parse_tool_content(tool_result.content)
            if isinstance(parsed, dict):
                if parsed.get("answer"):
                    answers.append(str(parsed["answer"]))
                for item in parsed.get("results", []) or []:
                    if isinstance(item, dict):
                        sources.append(item)
                writer(
                    {
                        "type": "search_results",
                        "query": parsed.get("query", query),
                        "answer": parsed.get("answer", ""),
                        "sources": parsed.get("results", []),
                    }
                )
            produced_messages.append(tool_result)
            messages.append(tool_result)

    summary = _last_ai_content(produced_messages) or "\n".join(answers) #先尝试获取最后一条非空的模型文本；如果取不到，就把收集到的工具答案用换行符连接起来
    result = {
        "ok": True,
        "summary": summary,
        "queries": queries,
        "sources": _dedupe_sources(sources), #去重后的来源 _dedupe_sources(sources) 按 URL 去重，也会跳过没有有效 URL 的条目。
        "messages": produced_messages,
        "tool_events": tool_events,
    }
    writer(
        {
            "type": "search_summary",
            "summary": result["summary"],
            "queries": result["queries"],
            "sources": result["sources"],
        }
    )
    return result

def _execute_search_tool(call: dict[str, Any]) -> ToolMessage:
    tool = build_web_search_tool()
    name = call.get("name", "")
    args = call.get("args") or {}
    if name != tool.name:
        result = {"ok": False, "error": f"unknown tool: {name}"}
    else:
        try:
            result = tool.invoke(args)
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False),
        name=name,
        tool_call_id=call.get("id") or f"{name}-call",
    )

def _tool_result_event(tool_message: ToolMessage) -> dict[str, Any]:
    parsed = _parse_tool_content(tool_message.content)
    return {"type": "tool_result", "node": "searchAgent", "name": tool_message.name, "result": parsed}

def _parse_tool_content(content: Any) -> Any:
    try:
        return json.loads(str(content))
    except json.JSONDecodeError:
        return content

def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped = []
    for source in sources:
        url = str(source.get("url", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(source)
    return deduped

def _last_ai_content(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            continue
        content = getattr(message, "content", "")
        if content:
            return str(content)
    return ""

