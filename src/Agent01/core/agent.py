from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator #Iterator：表示“迭代器类型”，可以逐个产生数据

from dotenv import load_dotenv
from langgraph.graph import add_messages

from Agent01.core.checkpoint import CheckpointManager, load_resume_inputs, normalize_checkpoint_mode

from Agent01.core.paths import default_workspace
from Agent01.core.state import RuntimeState
from Agent01.tools import build_tools
from Agent01.graph.workflow import build_workflow

def create_runtime(
    workspace: Path | None = None,
    *,
    approval_mode: str = "inline",
    approval_handler=None,
    checkpoint_mode: str | None = None,
    resume_from: Path | None = None,
) -> RuntimeState:
    load_dotenv() #加载项目配置，供下面的 AGENT_BASH_* 环境变量读取
    #确定本次 Agent 使用哪个工作区，确保该工作区存在，然后创建一个 RuntimeState 工作区状态对象
    selected = workspace or resume_from or default_workspace()
    selected.mkdir(parents=True, exist_ok=True) #parents=True 如果上层目录不存在，就一起创建。
    return RuntimeState( 
        workspace=selected, 
        approval_mode=approval_mode, 
        approval_handler=approval_handler,
        #命令执行参数保存在 RuntimeState，工具调用时统一读取。
        bash_default_timeout_seconds=_env_int("AGENT_BASH_DEFAULT_TIMEOUT_SECONDS", 120),
        bash_max_timeout_seconds=_env_int("AGENT_BASH_MAX_TIMEOUT_SECONDS", 600),
        bash_max_output_chars=_env_int("AGENT_BASH_MAX_OUTPUT_CHARS", 6000),
        bash_env_file=_env_path("AGENT_BASH_ENV_FILE"),
        #显式参数优先；没有传入时读取环境配置，非法模式回退为 light。
        checkpoint_mode=normalize_checkpoint_mode(checkpoint_mode or os.getenv("AGENT_CHECKPOINT_MODE", "light")),
        resume_from=resume_from,
    )

def stream_agent_events(
    task: str | None = None,
    *,
    workspace: Path | None = None,
    max_attempts: int = 3,
    approval_mode: str = "inline",
    approval_handler=None,
    checkpoint_mode: str | None = None,
    resume_workspace: Path | None = None,
) -> Iterator[dict[str, Any]]:
    #恢复任务时复用原工作区，不创建新的任务目录。
    resume_path = resume_workspace.expanduser() if resume_workspace is not None else None
    selected_workspace = resume_path or workspace
    state = create_runtime(
        selected_workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_from=resume_path,
    )
    workflow = build_workflow()
    yield {"type": "workspace", "path": str(state.workspace)}

    #恢复时加载旧进度；普通启动时构造一份空的初始状态。
    if resume_path is not None:
        inputs, resume_event = load_resume_inputs(state, task=task, max_attempts=max_attempts)
        yield {"type": "custom_event", "event": resume_event}
    else:
        inputs = {
            "task": task or "",
            "runtime": state,
            "messages": [],
            "attempts": 0,
            "max_attempts": max_attempts,
        }

    #维护完整状态副本：工作流 updates 只包含当前节点修改的字段。
    current_state: dict[str, Any] = dict(inputs)
    manager = CheckpointManager(state, task=str(current_state.get("task", "")))
    manager.save(current_state, status="started", latest_node="start")
    latest_node = "start"

    try:
        for mode, event in workflow.stream(inputs, stream_mode=["updates", "custom"]):
            if mode == "custom":
                manager.save(current_state, status="running", latest_node=latest_node, event={"mode": mode, "payload": event})
                yield {"type": "custom_event", "event": event}
            else:
                latest_node = _latest_graph_node(event) or latest_node
                _merge_graph_update(current_state, event)
                manager.save(current_state, status="running", latest_node=latest_node, event={"mode": mode, "payload": event})
                yield {"type": "graph_event", "event": event}
    #Ctrl+C 中断时保存已收集的状态，并把保存结果交给界面显示。
    except KeyboardInterrupt:
        saved = manager.save(current_state, status="interrupted", latest_node=latest_node)
        if saved:
            yield {"type": "custom_event", "event": saved}
        return

    #工作流正常结束后，记录完成状态。
    saved = manager.save(current_state, status="finished", latest_node=latest_node)
    if saved:
        yield {"type": "custom_event", "event": saved}


def _env_int(name: str, default: int) -> int:
    #读取正整数环境变量，格式错误或非正数时使用默认值。
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_path(name: str) -> Path | None:
    #空配置表示使用工作区默认环境文件；expanduser 将 ~ 展开为用户目录。
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser() if raw else None


def _latest_graph_node(event: Any) -> str | None:
    #updates 事件的外层键是节点名称，取最后一个作为最近运行节点。
    if isinstance(event, dict) and event:
        return str(next(reversed(event)))
    return None


def _merge_graph_update(state: dict[str, Any], event: Any) -> None:
    #消息按 LangGraph 的规则合并（同 ID 更新）；其他字段覆盖旧值。
    if not isinstance(event, dict):
        return
    for update in event.values():
        if not isinstance(update, dict):
            continue
        for key, value in update.items():
            if key == "messages":
                state["messages"] = list(add_messages(state.get("messages", []), value))
            else:
                state[key] = value
