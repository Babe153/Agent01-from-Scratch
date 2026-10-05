from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator #Iterator：表示“迭代器类型”，可以逐个产生数据

from dotenv import load_dotenv
from langgraph.graph import add_messages

from Agent01.core.checkpoint import CheckpointManager, load_resume_inputs, normalize_checkpoint_mode

from Agent01.core.paths import default_workspace
from Agent01.core.session import (
    append_assistant_turn,
    append_user_turn,
    build_session_context,
    load_or_create_session,
    save_session,
    session_started_event,
    session_turn_saved_event,
    session_turn_started_event,
)
from Agent01.core.state import RuntimeState
from Agent01.core.trace import TraceRecorder, normalize_trace_mode
from Agent01.tools import build_tools
from Agent01.graph.workflow import build_complex_workflow, build_entry_workflow

def create_runtime(
    workspace: Path | None = None,
    *,
    approval_mode: str = "inline",
    approval_handler=None,
    checkpoint_mode: str | None = None,
    resume_from: Path | None = None,
    trace_mode: str | None = None,
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
        #命令行或调用参数优先，否则读取环境变量；默认开启 Trace。
        trace_mode=normalize_trace_mode(trace_mode or os.getenv("AGENT_TRACE_MODE", "on")),
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
    trace_mode: str | None = None,
) -> Iterator[dict[str, Any]]:
    #恢复任务时复用原工作区，不创建新的任务目录。
    resume_path = resume_workspace.expanduser() if resume_workspace is not None else None
    #新输入先分类；恢复任务直接沿用已有工作区，跳过入口图。
    if resume_path is None:
        #默认按复杂任务处理，只有明确的 chat 决策才提前结束。
        route = "workflow"
        entry_state: dict[str, Any] = {"task": task or "", "messages": []}
        for mode, event in build_entry_workflow().stream(entry_state, stream_mode=["updates", "custom"]):
            if mode == "custom":
                yield {"type": "custom_event", "event": event}
                if isinstance(event, dict) and event.get("type") == "intent_decision":
                    route = str(event.get("route") or "workflow")
            else:
                _merge_graph_update(entry_state, event)
                yield {"type": "graph_event", "event": event}
        #轻量聊天在创建 runtime、工作区、Checkpoint 和 Trace 之前结束。
        if route == "chat":
            return

    selected_workspace = resume_path or workspace
    state = create_runtime(
        selected_workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_from=resume_path,
        trace_mode=trace_mode,
    )
    workflow = build_complex_workflow()
    yield {"type": "workspace", "path": str(state.workspace)}

    #恢复时加载旧进度；普通启动时构造一份空的初始状态。
    resumed = False
    resume_event: dict[str, Any] | None = None
    if resume_path is not None:
        inputs, resume_event = load_resume_inputs(state, task=task, max_attempts=max_attempts)
        resumed = True
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
    #Trace 记录本次运行的过程；Checkpoint 保存可供恢复的进度。
    trace = TraceRecorder(state, task=str(current_state.get("task", "")))
    trace.start(current_state, resumed=resumed, resume_event=resume_event)
    if resume_event is not None:
        trace.record_custom_event(resume_event)
    started_checkpoint = manager.save(current_state, status="started", latest_node="start")
    if started_checkpoint:
        trace.record_custom_event(started_checkpoint)
    latest_node = "start"

    try:
        for mode, event in workflow.stream(inputs, stream_mode=["updates", "custom"]):
            if mode == "custom":
                trace.record_custom_event(event)
                #普通事件只写 Trace；工具失败或需要审批时才额外保存进度。
                if _custom_event_needs_checkpoint(event):
                    saved = manager.save(current_state, status="running", latest_node=latest_node, event={"mode": mode, "payload": event})
                    if saved:
                        trace.record_custom_event(saved)
                yield {"type": "custom_event", "event": event}
            else:
                latest_node = _latest_graph_node(event) or latest_node
                _merge_graph_update(current_state, event)
                trace.record_graph_update(event)
                saved = manager.save(current_state, status="running", latest_node=latest_node, event={"mode": mode, "payload": event})
                if saved:
                    trace.record_custom_event(saved)
                yield {"type": "graph_event", "event": event}
    #Ctrl+C 中断时保存已收集的状态，并把保存结果交给界面显示。
    except KeyboardInterrupt:
        saved = manager.save(current_state, status="interrupted", latest_node=latest_node)
        if saved:
            trace.record_custom_event(saved)
            yield {"type": "custom_event", "event": saved}
        #中断也要结束 Trace，生成统计摘要和时间线。
        trace_event = trace.end(status="interrupted", latest_node=latest_node, final_state=current_state)
        if trace_event:
            yield {"type": "custom_event", "event": trace_event}
        return

    #工作流正常结束后，记录完成状态。
    saved = manager.save(current_state, status="finished", latest_node=latest_node)
    if saved:
        trace.record_custom_event(saved)
        yield {"type": "custom_event", "event": saved}
    trace_event = trace.end(status="finished", latest_node=latest_node, final_state=current_state)
    if trace_event:
        yield {"type": "custom_event", "event": trace_event}


def stream_session_events(
    task: str | None = None,
    *,
    session_workspace: Path | None = None,
    max_attempts: int = 3,
    approval_mode: str = "inline",
    approval_handler=None,
    checkpoint_mode: str | None = None,
    resume_workspace: Path | None = None,
    trace_mode: str | None = None,
) -> Iterator[dict[str, Any]]:
    """TUI 的多轮会话入口；同一 session_workspace 复用文件和对话记录。
    先加载 session、保存用户输入，再把 session_context 传给入口图分类。
    聊天直接保存回答；复杂任务调用 _stream_complex_workflow，并收集最终回答。
    这一入口即使只是聊天也会建立会话文件，但只有复杂任务生成 Checkpoint/Trace。
    与旧的 stream_agent_events 不同，此版本会话入口传入 resume 后仍先分类。
    """
    workspace = (resume_workspace or session_workspace or default_workspace()).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    session = load_or_create_session(workspace)
    resumed = resume_workspace is not None
    yield {"type": "custom_event", "event": session_started_event(workspace, session, resumed=resumed)}
    yield {"type": "workspace", "path": str(workspace)}

    if not task:
        return

    #先保存用户输入：即使后续模型或工具失败，输入也已落盘。
    turn = append_user_turn(session, task)
    save_session(workspace, session)
    yield {"type": "custom_event", "event": session_turn_started_event(workspace, session, turn=turn, task=task)}
    #每轮重新整理历史并传入模型；模型 API 本身不会自动记住上一轮。
    session_context = build_session_context(workspace, session)

    route = "workflow"
    entry_state: dict[str, Any] = {
        "task": task or "",
        "messages": [],
        "session_id": session.get("session_id", ""),
        "session_turn": turn,
        "session_context": session_context,
    }
    for mode, event in build_entry_workflow().stream(entry_state, stream_mode=["updates", "custom"]):
        if mode == "custom":
            yield {"type": "custom_event", "event": event}
            if isinstance(event, dict) and event.get("type") == "intent_decision":
                route = str(event.get("route") or "workflow")
        else:
            _merge_graph_update(entry_state, event)
            yield {"type": "graph_event", "event": event}

    if route == "chat":
        response = str(entry_state.get("chat_response") or entry_state.get("final_answer") or "")
        append_assistant_turn(session, turn=turn, route="chat", content=response, summary=response)
        save_session(workspace, session)
        yield {"type": "custom_event", "event": session_turn_saved_event(workspace, session, turn=turn, route="chat")}
        return

    workflow_events = _stream_complex_workflow(
        task=task,
        workspace=workspace,
        max_attempts=max_attempts,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_workspace=resume_workspace,
        trace_mode=trace_mode,
        session=session,
        turn=turn,
        session_context=session_context,
    )
    final_answer = ""
    for event in workflow_events:
        final_answer = _final_answer_from_event(event) or final_answer
        yield event

    append_assistant_turn(session, turn=turn, route="workflow", content=final_answer, summary=final_answer)
    save_session(workspace, session)
    yield {"type": "custom_event", "event": session_turn_saved_event(workspace, session, turn=turn, route="workflow")}


def _stream_complex_workflow(
    *,
    task: str | None,
    workspace: Path,
    max_attempts: int,
    approval_mode: str,
    approval_handler,
    checkpoint_mode: str | None,
    resume_workspace: Path | None,
    trace_mode: str | None,
    session: dict[str, Any] | None = None,
    turn: int | None = None,
    session_context: str = "",
) -> Iterator[dict[str, Any]]:
    """在指定会话工作区执行一轮复杂任务，沿用审批、Checkpoint 和 Trace。
    恢复时先加载旧任务状态，再注入当前 session_id、session_turn、session_context。
    工作流每次从入口启动；会话历史通过文本上下文传入，而不是永久复用模型对象。
    逐条 yield 后端事件，由调用方显示并提取 final_answer。
    """
    resume_path = resume_workspace.expanduser() if resume_workspace is not None else None
    state = create_runtime(
        workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_from=resume_path,
        trace_mode=trace_mode,
    )
    workflow = build_complex_workflow()

    resumed = False
    resume_event: dict[str, Any] | None = None
    if resume_path is not None:
        inputs, resume_event = load_resume_inputs(state, task=task, max_attempts=max_attempts)
        resumed = True
        yield {"type": "custom_event", "event": resume_event}
    else:
        inputs = {
            "task": task or "",
            "runtime": state,
            "messages": [],
            "attempts": 0,
            "max_attempts": max_attempts,
        }

    #将会话信息注入图状态；metadata 另存标识用于追踪。
    if session is not None:
        inputs["session_id"] = session.get("session_id", "")
    if turn is not None:
        inputs["session_turn"] = turn
    if session_context:
        inputs["session_context"] = session_context
    metadata = dict(inputs.get("metadata", {}))
    if session is not None:
        metadata["session_id"] = session.get("session_id", "")
    if turn is not None:
        metadata["session_turn"] = turn
    if metadata:
        inputs["metadata"] = metadata

    current_state: dict[str, Any] = dict(inputs)
    manager = CheckpointManager(state, task=str(current_state.get("task", "")))
    trace = TraceRecorder(state, task=str(current_state.get("task", "")))
    trace.start(current_state, resumed=resumed, resume_event=resume_event)
    if resume_event is not None:
        trace.record_custom_event(resume_event)
    started_checkpoint = manager.save(current_state, status="started", latest_node="start")
    if started_checkpoint:
        trace.record_custom_event(started_checkpoint)
    latest_node = "start"

    try:
        for mode, event in workflow.stream(inputs, stream_mode=["updates", "custom"]):
            if mode == "custom":
                trace.record_custom_event(event)
                if _custom_event_needs_checkpoint(event):
                    saved = manager.save(current_state, status="running", latest_node=latest_node, event={"mode": mode, "payload": event})
                    if saved:
                        trace.record_custom_event(saved)
                yield {"type": "custom_event", "event": event}
            else:
                latest_node = _latest_graph_node(event) or latest_node
                _merge_graph_update(current_state, event)
                trace.record_graph_update(event)
                saved = manager.save(current_state, status="running", latest_node=latest_node, event={"mode": mode, "payload": event})
                if saved:
                    trace.record_custom_event(saved)
                yield {"type": "graph_event", "event": event}
    except KeyboardInterrupt:
        saved = manager.save(current_state, status="interrupted", latest_node=latest_node)
        if saved:
            trace.record_custom_event(saved)
            yield {"type": "custom_event", "event": saved}
        trace_event = trace.end(status="interrupted", latest_node=latest_node, final_state=current_state)
        if trace_event:
            yield {"type": "custom_event", "event": trace_event}
        return

    saved = manager.save(current_state, status="finished", latest_node=latest_node)
    if saved:
        trace.record_custom_event(saved)
        yield {"type": "custom_event", "event": saved}
    trace_event = trace.end(status="finished", latest_node=latest_node, final_state=current_state)
    if trace_event:
        yield {"type": "custom_event", "event": trace_event}


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


def _custom_event_needs_checkpoint(event: Any) -> bool:
    #筛选值得立即保存进度的自定义事件，减少文件扫描和 Git 快照次数。
    if not isinstance(event, dict):
        return False
    if event.get("type") != "tool_result":
        return False
    result = event.get("result")
    if not isinstance(result, dict):
        return False
    return result.get("ok") is False or bool(result.get("requires_approval"))


def _final_answer_from_event(event: dict[str, Any]) -> str:
    """只从 graph_event 的 final 节点更新里提取 final_answer。
    其他事件返回空字符串，让调用方保留上一次已提取到的答案。
    """
    if event.get("type") != "graph_event":
        return ""
    payload = event.get("event")
    if not isinstance(payload, dict):
        return ""
    update = payload.get("final")
    if not isinstance(update, dict):
        return ""
    return str(update.get("final_answer") or "")
