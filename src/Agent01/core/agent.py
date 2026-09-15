from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator #Iterator：表示“迭代器类型”，可以逐个产生数据

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from Agent01.core.paths import default_workspace
from Agent01.core.state import RuntimeState
from Agent01.prompts.version1 import VERSION1_SYSTEM_PROMPT
from Agent01.providers.openai_provider import create_model
from Agent01.tools import build_tools

def create_runtime(workspace: Path | None = None) -> RuntimeState:
    #确定本次 Agent 使用哪个工作区，确保该工作区存在，然后创建一个 RuntimeState 工作区状态对象
    selected = workspace or default_workspace()
    selected.mkdir(parents=True, exist_ok=True) #parents=True 如果上层目录不存在，就一起创建。
    return RuntimeState(workspace=selected)

def create_code_agent(state: RuntimeState):
    #创建模型，把模型、工具和系统提示词交给 LangChain 的 create_agent()，最终返回一个组装完成的 Agent
    model = create_model()
    return create_agent(
        model=model,
        tools=build_tools(state),
        system_prompt=VERSION1_SYSTEM_PROMPT,
    )

def stream_agent_events(task: str, *, workspace: Path | None = None) -> Iterator[dict[str, Any]]:
    state = create_runtime(workspace)
    agent = create_code_agent(state)
    yield {"type": "workspace", "path": str(state.workspace)}

    inputs = {"messages": [HumanMessage(content=task)]}
    for event in agent.stream(inputs, stream_mode="updates"):
        #把 inputs 交给 Agent 执行，并以流式形式返回执行过程中的更新
        yield {"type": "agent_event", "event": event}




