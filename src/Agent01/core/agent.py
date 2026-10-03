from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator #Iterator：表示“迭代器类型”，可以逐个产生数据

from dotenv import load_dotenv

from Agent01.core.paths import default_workspace
from Agent01.core.state import RuntimeState
from Agent01.tools import build_tools
from Agent01.graph.workflow import build_workflow

def create_runtime(
    workspace: Path | None = None,
    *,
    approval_mode: str = "inline",
    approval_handler=None,
) -> RuntimeState:
    load_dotenv() #加载项目配置，供下面的 AGENT_BASH_* 环境变量读取
    #确定本次 Agent 使用哪个工作区，确保该工作区存在，然后创建一个 RuntimeState 工作区状态对象
    selected = workspace or default_workspace()
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
    )

def stream_agent_events(
    task: str,
    *,
    workspace: Path | None = None,
    max_attempts: int = 3,
    approval_mode: str = "inline",
    approval_handler=None,
) -> Iterator[dict[str, Any]]:
    state = create_runtime(workspace, approval_mode=approval_mode, approval_handler=approval_handler)
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



