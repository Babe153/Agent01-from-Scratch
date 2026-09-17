from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
#负责把一个普通的 Python 函数包装、注册为 LangChain 中可供 LLM 调用的工具
from langgraph.config import get_stream_writer
#让节点在运行中向外报告进度 调用它，会取得当前 LangGraph 执行上下文中的一个“事件发送函数”

from Agent01.core.state import RuntimeState
from Agent01.graph.state import Agent01GraphState, TodoItem, VerificationResult
from Agent01.prompts.version2 import ACTOR_PROMPT, FINAL_PROMPT, PLANNER_PROMPT
from Agent01.providers.openai_provider import create_model
from Agent01.tools import build_tools
from Agent01.tools.bash_tool import run_bash
from Agent01.tools.todo_tool import update_todo, write_todos


#一个具体示例“生命游戏”的具体prompt
DEFAULT_GAME_OF_LIFE_TODOS = [
    "Write test_game_of_life.py first with tests for underpopulation, survival, reproduction, overpopulation, and blinker oscillator.",
    "Run python -m pytest -q and confirm the tests fail before implementation.",
    "Implement game_of_life.py with pure functions and a small CLI demo mode.",
    "Run python -m pytest -q until all tests pass.",
    "Run python game_of_life.py --demo --steps 3 to verify the terminal demo.",
]

DEFAULT_GAME_OF_LIFE_CRITERIA = [
    "Implements Conway's four rules correctly.",
    "Includes a blinker oscillator test.",
    "Provides a terminal demo mode runnable with --demo --steps 3.",
    "All verifier commands exit with code 0.",
]

DEFAULT_GAME_OF_LIFE_COMMANDS = [
    "python -m pytest -q",
    "python game_of_life.py --demo --steps 3",
]

def _extract_json(text: str) -> dict[str, Any] | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) #尝试找到 Markdown 代码块中的 JSON re.search()找到返回匹配对象 找不到时会返回None
    raw = fenced.group(1) if fenced else text #将第一个匹配到的对象赋值给raw 不是json的话就赋值原始text
    start = raw.find("{") #find("{")：找第一个 {
    end = raw.rfind("}") #rfind("}")：找最后一个 }
    if start == -1 or end == -1 or end < start:
        return None #没有完整的花括号，或顺序不对，就直接判定提取失败
    try:
        parsed = json.loads(raw[start : end + 1]) #解析首尾花括号内的内容 变成python字典
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None #最后确认内容是字典 不是的话返回None


def _default_plan(task: str) -> dict[str, Any]:
    #“生命游戏”这部分是为特定演示任务硬编码的内容，不是 Agent 框架必需的设计
    if "生命游戏" in task or "Game of Life" in task or "Conway" in task:
        return {
            "plan_summary": "Use TDD to build a dependency-free terminal Conway's Game of Life implementation.",
            "todos": DEFAULT_GAME_OF_LIFE_TODOS,
            "acceptance_criteria": DEFAULT_GAME_OF_LIFE_CRITERIA,
            "verification_commands": DEFAULT_GAME_OF_LIFE_COMMANDS,
        }
    return {
        "plan_summary": "Create a small dependency-free Python program and verify it with a smoke run.",
        "todos": [
            "Create a Python file for the requested task.",
            "Add a non-interactive demo or smoke mode.",
            "Run the generated file with Python.",
        ],
        "acceptance_criteria": ["Generated code exists.", "A Python smoke command exits with code 0."],
        "verification_commands": ["python -m pytest -q"],
    }

def _todo_items(todos: list[str]) -> list[TodoItem]: #返回一个列表，每一项符合 TodoItem 定义的字典结构
    #把一组任务文字，转换成带编号、状态和备注的待办列表
    return [
        {"id": f"todo-{idx}", "content": todo, "status": "pending", "note": ""}
        for idx, todo in enumerate(todos, start=1) #enumerate() 会给每一项配上编号，start=1 表示从 1 开始
        #第一次：idx = 1，todo = "创建文件"
        #第二次：idx = 2，todo = "运行测试"
    ]

def planner_node(state: Agent01GraphState) -> dict[str, Any]:
    task = state["task"]
    attempts = state.get("attempts", 0)
    previous_error = state.get("last_error", "")
    model = create_model() #创建了一个模型来当planner
    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(
            content=(
                f"Task: {task}\n"
                f"Attempt: {attempts + 1}\n"
                f"Previous verifier failure, if any:\n{previous_error}\n"
                "Return only JSON."
            )
        ),
    ]
    response = model.invoke(messages)
    parsed = _extract_json(str(response.content)) or _default_plan(task)

    plan_summary = str(parsed.get("plan_summary") or _default_plan(task)["plan_summary"])
    todos = [str(item) for item in parsed.get("todos") or _default_plan(task)["todos"]]
    acceptance_criteria = [
        str(item) for item in parsed.get("acceptance_criteria") or _default_plan(task)["acceptance_criteria"]
    ]
    verification_commands = _verification_commands_for_task(task, parsed) #------------------------------------------------------------------------------------------------------
    todo_result = write_todos(todos, acceptance_criteria, verification_commands)

    return { #return 返回给 LangGraph，由它更新工作流的 state
        "plan_summary": plan_summary,
        "todos": _todo_items(todo_result["todos"]),
        "acceptance_criteria": todo_result["acceptance_criteria"],
        "verification_commands": todo_result["verification_commands"],
        "messages": [response],
        "metadata": {"planner_raw": response.content}, #原始模型回复
    }

def actor_node(state: Agent01GraphState) -> dict[str, Any]:
    runtime = state["runtime"] #获取到RuntimeState 从而得到工作区路径以及文件相关信息
    todos = [dict(todo) for todo in state.get("todos", [])] #得到计划步骤
    model = create_model()
    actor_tools = build_tools(runtime) + [_build_todo_update_tool(todos)] #创建并组合 actor 可以使用的工具列表  #------------------------------------------------------------------------------------------------------
    actor = model.bind_tools(actor_tools) #绑定工具到模型
    todo_text = "\n".join(
        f"- {todo['id']} [{todo['status']}] {todo['content']}" for todo in todos #把 todos 列表转换成一段多行文本，方便放进提示词给模型阅读。
    )
    criteria_text = "\n".join(f"- {item}" for item in state.get("acceptance_criteria", [])) #同
    commands_text = "\n".join(f"- {command}" for command in state.get("verification_commands", [])) #同
    failure_text = state.get("last_error", "") #从 state 中获取 "last_error" 对应的值，赋给 failure_text
    messages = [
        SystemMessage(content=ACTOR_PROMPT),
        HumanMessage(
            content=(
                f"Task: {state['task']}\n\n"
                f"Plan: {state.get('plan_summary', '')}\n\n"
                f"Todos:\n{todo_text}\n\n"
                f"Acceptance criteria:\n{criteria_text}\n\n"
                f"Verifier commands:\n{commands_text}\n\n"
                f"Previous verifier failure:\n{failure_text}\n\n"
                "Implement the plan now using tools. Only run non-interactive commands. "
                "Use the verifier commands exactly when checking the final result. "
                "Stop after a concise implementation summary."
            )
        ),
    ]

    produced_messages = []
    writer = _get_writer() #------------------------------------------------------------------------------------------------------
    writer(
        {
            "type": "plan_snapshot",
            "node": "actor",
            "plan_summary": state.get("plan_summary", ""),
            "todos": todos,
            "verification_commands": state.get("verification_commands", []),
        }
    )
    for _ in range(10):
        response = actor.invoke(messages)
        produced_messages.append(response) #写入信息
        messages.append(response) #加入状态信息 
        tool_calls = getattr(response, "tool_calls", None) or [] #看看叫没叫工具 叫了什么工具
        if not tool_calls:
            break #没叫工具就退出循环 因为可能是最终回复 任务执行完了llm就不调用工具了
        for call in tool_calls: #遍历调用的每个工具
            writer({"type": "tool_call", "name": call.get("name"), "args": call.get("args", {})})                  #这里是怎么把call写成字典的 一次一个tool吗
            tool_result, todos = _execute_actor_tool(runtime, todos, call) #------------------------------------------------------------------------------------------------------
            writer(_tool_result_event(tool_result)) #------------------------------------------------------------------------------------------------------
            if call.get("name") == "TodoUpdateTool":
                writer(
                    {
                        "type": "todo_update",
                        "plan_summary": state.get("plan_summary", ""),
                        "todos": todos,
                        "verification_commands": state.get("verification_commands", []),
                    }
                )
            produced_messages.append(tool_result)
            messages.append(tool_result)
    else:
        produced_messages.append(
            AIMessage(content="Actor stopped after the maximum tool loop count; verifier will evaluate current files.")
        )

    summary = ""
    for message in reversed(produced_messages):
        content = getattr(message, "content", "")
        if content and not getattr(message, "name", None):
            summary = str(content)
            break

    return {
        "messages": produced_messages,
        "todos": todos or state.get("todos", []),
        "last_actor_summary": summary,
    }

def _build_todo_update_tool(todos: list[dict[str, str]]) -> StructuredTool:
    #把 update_todo() 包装成一个模型可调用的工具
    return StructuredTool.from_function(
        name="TodoUpdateTool",
        func=lambda todo_id, status, note="": update_todo(todos, todo_id, status, note),
        description="Update one existing todo status. Args: todo_id, status, optional note.",
    )

def _execute_actor_tool(runtime: RuntimeState, todos: list[dict[str, str]], call: dict[str, Any]):
    #真正开始执行actor的工具
    from langchain_core.messages import ToolMessage

    #获取工具名和参数
    name = call["name"]
    args = call.get("args") or {}

    if name == "TodoUpdateTool":
        result = update_todo(todos, args.get("todo_id", ""), args.get("status", ""), args.get("note", ""))
        if result.get("ok"):
            todos = result["todos"]
    else:
        tools = {tool.name: tool for tool in build_tools(runtime)}
        tool = tools.get(name)
        if tool is None:
            result = {"ok": False, "error": f"unknown tool: {name}"}
        else:
            try:
                result = tool.invoke(args)
            except Exception as exc:  # Keep tool errors inside the agent loop.
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return ToolMessage(content=json.dumps(result, ensure_ascii=False), name=name, tool_call_id=call["id"]), todos



