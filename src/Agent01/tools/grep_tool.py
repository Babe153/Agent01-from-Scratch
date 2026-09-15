from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from Agent01.core.state import RuntimeState
from Agent01.tools.file_tools import display_path, read_text_lossy, resolve_workspace_path

SKIP_DIRS = {".git", ".Agent01", ".venv", "__pycache__", ".pytest_cache"} #不去读取这些结尾的文件

def _iter_files(root: Path, glob_pattern: str | None) -> list[Path]:
    #从 root 目录开始递归寻找目录中的所有文件，排除不该搜索的目录，再按照 glob_pattern 筛选文件类型，最后返回符合要求的文件路径列表
    files: list[Path] = []
    for path in root.rglob("*"):
        #rglob("*") 表示：递归遍历 root 里面的所有文件和目录。 找出来的既有文件，也有目录
        if not path.is_file():
            continue #不是文件不要它 继续
        if any(part in SKIP_DIRS for part in path.parts):
            continue #是ignore文件不要它 继续
        if glob_pattern and not fnmatch.fnmatch(path.name, glob_pattern) and not fnmatch.fnmatch(str(path), glob_pattern):
            continue #如果传了筛选规则，而且文件名不匹配，完整路径也不匹配，那么跳过这个文件
        files.append(path) #把文件加入files列表 返回
    return files



def grep(
    state: RuntimeState,
    pattern: str,
    path: str = ".", #指定从哪里搜索，默认是 "." 表示当前工作区目录
    glob: str | None = None,
    head_limit: int | str = 50, #最多返回多少条匹配结果，默认是 50 条
    ignore_case: bool = False, #是否忽略英文字母大小写，默认不忽略
) -> dict[str, Any]:
    if not pattern:
        #校验pattern
        return {"ok": False, "error": "pattern must not be empty"}
    try:
        #校验head_limit
        head_limit_value = int(head_limit)
    except (TypeError, ValueError):
        return {"ok": False, "error": "head_limit must be an integer"}
    if head_limit_value <= 0:
        return {"ok": False, "error": "head_limit must be > 0"}

    root = resolve_workspace_path(state, path)
    if root.is_file():
        candidates = [root] #如果是一个文件，就把它放进候选文件列表
    elif root.is_dir():
        candidates = _iter_files(root, glob) #如果是目录 列出所有匹配的文件 返给候选一个列表
    else:
        return {"ok": False, "error": f"path does not exist: {display_path(state, root)}"}

    flags = re.IGNORECASE if ignore_case else 0 #re.IGNORECASE 表示忽略大小写校验
    try:
        regex = re.compile(pattern, flags) #把字符串形式的 pattern 编译成正则表达式对象
    except re.error as exc: #如果正则表达式格式错误，就捕获 re.error，并把异常对象保存到 exc
        return {"ok": False, "error": f"invalid regex: {exc}"}

    matches: list[dict[str, Any]] = [] #创建一个空列表，用于保存匹配结果 每一条结果是一个字典
    for file in candidates: #逐个文件读候选文件里的文件内容
        lines = read_text_lossy(file).splitlines() #文件内容分成具体行数 lines 是文件中的每一行组成的列表
        for idx, line in enumerate(lines, start=1): #遍历文件中的每一行，同时生成行号
            #enumerate(lines, start=1) 会依次得到：
            #idx = 1, line = "import os"
            #idx = 2, line = "class RuntimeState:"
            #idx = 3, line = "    pass"

            if regex.search(line): #使用编译好的正则表达式搜索当前这一行
                matches.append({"path": display_path(state, file), "line": idx, "text": line}) #如果当前行匹配，就向 matches 中添加一条记录 哪个文件 第几行 这一行的内容
                if len(matches) >= head_limit_value: #检查当前收集的匹配数量是否已经达到上限
                    return {"ok": True, "pattern": pattern, "matches": matches, "truncated": True} #"truncated": True表示搜索因为达到数量上限而提前结束，后面可能还有结果

    return {"ok": True, "pattern": pattern, "matches": matches, "truncated": False}

