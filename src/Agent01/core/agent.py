from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator #Iterator：表示“迭代器类型”，可以逐个产生数据

from Agent01.core.paths import default_workspace
from Agent01.core.state import RuntimeState
from Agent01.tools import build_tools
from Agent01.graph.workflow import build_workflow

def create_runtime(workspace: Path | None = None) -> RuntimeState:
    #确定本次 Agent 使用哪个工作区，确保该工作区存在，然后创建一个 RuntimeState 工作区状态对象
    selected = workspace or default_workspace()
    selected.mkdir(parents=True, exist_ok=True) #parents=True 如果上层目录不存在，就一起创建。
    return RuntimeState(workspace=selected)

def stream_agent_events(
    task: str,
    *,
    workspace: Path | None = None,
    max_attempts: int = 3,
) -> Iterator[dict[str, Any]]:
    state = create_runtime(workspace)
    workflow = build_workflow()
    yield {"type": "workspace", "path": str(state.workspace)}

    inputs: dict[str, Any] = {
        "task": task,
        "runtime": state,
        "messages": [],
        "attempts": 0,
        "max_attempts": max_attempts,
    }
    for mode, event in workflow.stream(inputs, stream_mode=["updates", "custom"]):
        if mode == "custom":
            yield {"type": "custom_event", "event": event}
        else:
            yield {"type": "graph_event", "event": event}




