from __future__ import annotations
#导入 annotations 让类型注解延后处理

import difflib
#用来比较修改前后的内容，告诉你删了什么、加了什么

from pathlib import Path
#pathlib 是库，Path 是其中的一个类。它把路径包装成对象 处理文件路径
from typing import Any
#用于类型注解 允许使用 Any 表示“这里可以是任意类型”。

from Agent01.core.state import RuntimeState

MAX_READ_LINES = 2000 #一次最多向 Agent 返回 2000 行文本，避免内容太多
TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "gbk") #三种文本编码元组 后面代码会遍历依次尝试 确保读文件正常

def _strip_workspace_prefix(file_path: str) -> str:
    #统一路径格式，并去掉路径开头的 workspace/
    normalized = file_path.replace("\\", "/").strip()
    #.replace("\\", "/")：把反斜杠 \ 换成正斜杠 /。Python 字符串里用 "\\" 表示一个反斜杠
    #.strip()：去掉字符串两端的空格、换行等空白字符
    while normalized in {"workspace", "./workspace"} or normalized.startswith(("workspace/", "./workspace/")):
        if normalized in {"workspace", "./workspace"}:
            normalized = "."
        elif normalized.startswith("./workspace/"):
            normalized = normalized[len("./workspace/") :] #./workspace/ 之后的内容
        else:
            normalized = normalized[len("workspace/") :] #workspace/ 之后的内容
    return normalized

def read_text_lossy(path: Path) -> str:
    #尝试用不同编码读取文件；如果都解码失败，就把无法识别的字符换成 �，尽量返回文本
    last_error: UnicodeDecodeError | None = None
    #定义一个变量，用来保存最近一次解码错误 不然就是None
    #UnicodeDecodeError 是一种异常：文件里的字节无法按照指定编码转换成文字
    for encoding in TEXT_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        return path.read_text(encoding="utf-8", errors="replace") #再用utf-8读取 遇到无法解码的字节，使用替代字符 �，继续读取
    return path.read_text(encoding="utf-8")

def resolve_workspace_path(state: RuntimeState, file_path: str) -> Path:
    #把传入的路径转换成工作区内的文件路径，并检查有没有越界
    raw = Path(_strip_workspace_prefix(file_path)).expanduser()
    if not raw.is_absolute():
        raw = state.workspace / raw
    return state.assert_workspace_path(raw)

def display_path(state: RuntimeState, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(state.workspace.resolve())) #取得相对于工作区的路径 /project/workspace/notes/a.txt → notes/a.txt
    except ValueError:
        return str(path)


def read_file(
    state: RuntimeState,
    file_path: str,
    offset: int | str = 0, #跳过前面多少行，再开始读取
    limit: int | str = MAX_READ_LINES, #limit 决定最多读多少行
) -> dict[str, Any]:

    #校验
    path = resolve_workspace_path(state, file_path)
    if not path.exists():
        return {"ok": False, "error": f"file does not exist: {display_path(state, path)}"}
    if not path.is_file():
        return {"ok": False, "error": f"path is not a file: {display_path(state, path)}"}

    #校验
    try:
        offset_value = int(offset)
        limit_value = int(limit)
    except (TypeError, ValueError):
        return {"ok": False, "error": "offset and limit must be integers"}
    if offset_value < 0:
        return {"ok": False, "error": "offset must be >= 0"}
    if limit_value <= 0:
        return {"ok": False, "error": "limit must be > 0"}

    text = read_text_lossy(path) #用不同编码读文件 读完返回给text
    lines = text.splitlines() #把文本按换行拆成列表，每一行成为一个元素
    limit_value = min(limit_value, MAX_READ_LINES) #取两个数中较小的一个，再赋值给 limit_value 确保不超过最大读取行数
    selected = lines[offset_value : offset_value + limit_value]
    complete = offset_value == 0 and len(selected) == len(lines) #判断这一次有没有把整个文件的内容都选出来，完整返回给 Agent 全部选中 → complete = True 只选中一部分 → complete = False
    state.record_read(path, complete=complete) 

    numbered = "\n".join(f"{offset_value + idx + 1}: {line}" for idx, line in enumerate(selected)) #给选中的每一行加上行号，再用换行符拼成一个字符串
    
    return {
        "ok": True,
        "path": display_path(state, path),
        "total_lines": len(lines),
        "offset": offset_value,
        "limit": limit_value,
        "complete": complete,
        "content": numbered,
    }


