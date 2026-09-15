from __future__ import annotations

from langchain_core.tools import StructuredTool
#负责把一个普通的 Python 函数包装、注册为 LangChain 中可供 LLM 调用的工具

from Agent01.core.state import RuntimeState
from Agent01.tools.bash_tool import run_bash
from Agent01.tools.file_tools import edit_file, read_file, write_file
from Agent01.tools.grep_tool import grep


def build_tools(state: RuntimeState) -> list[StructuredTool]:
    return [
        #StructuredTool 是 LangChain 提供的工具类，from_function() 是它的类方法，用于：根据一个普通 Python 函数，创建一个 LangChain 可以识别和调用的工具对象。
        StructuredTool.from_function(
            name="FileReadTool",
            func=lambda file_path, offset=0, limit=2000: read_file(state, file_path, offset, limit),
            #！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！
            #这里用lambda的意义是提前把state:RuntimeState塞给函数 不让llm去生成 其他参数会被llm覆盖
            #！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！
            description="Read a UTF-8 text file inside the workspace. Supports offset and limit.",
        ),
        StructuredTool.from_function(
            name="FileWriteTool",
            func=lambda file_path, content: write_file(state, file_path, content),
            description="Create a new file or rewrite an existing file inside the workspace.",
        ),
        StructuredTool.from_function(
            name="FileEditTool",
            func=lambda file_path, old_text, new_text: edit_file(state, file_path, old_text, new_text),
            description="Edit an existing workspace file by replacing one unique old_text snippet.",
        ),
        StructuredTool.from_function(
            name="GrepTool",
            func=lambda pattern, path=".", glob=None, head_limit=50, ignore_case=False: grep(
                state, pattern, path, glob, head_limit, ignore_case
            ),
            description="Search workspace text files by regex pattern and return matching lines.",
        ),
        StructuredTool.from_function(
            name="BashTool",
            func=lambda command, timeout_seconds=10: run_bash(state, command, timeout_seconds),
            description="Run a safe development shell command inside the workspace with timeout and output capture.",
        ),
    ]

