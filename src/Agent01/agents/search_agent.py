from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from Agent01.graph.state import Agent01GraphState #运行状态
from Agent01.prompts.version3 import SEARCH_AGENT_PROMPT #提示词
from Agent01.providers.openai_provider import create_model #创建模型方法
from Agent01.tools.web_search_tool import build_web_search_tool #引入专用工具

Writer = Callable[[dict[str, Any]], None]