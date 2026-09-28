from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from Agent01.core.state import RuntimeState
from Agent01.graph.state import Agent01GraphState #运行状态
from Agent01.prompts.version3 import CODE_AGENT_PROMPT
from Agent01.providers.openai_provider import create_model #创建模型方法
from Agent01.tools import build_tools
from Agent01.tools.todo_tool import update_todo



