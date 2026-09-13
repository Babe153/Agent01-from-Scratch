from __future__ import annotations
#导入 annotations 让类型注解延后处理

from pathlib import Path
#从 Python 自带的 pathlib 模块中，导入处理文件和文件夹路径的 Path 类

def find_project_root(start: Path | None = None) -> Path:
    #定义一个找到项目路径的方法 传入path 如果没有传入path那就用None初始化
    """Find the nearest project root marker from ``start`` upward."""
    current = (start or Path.cwd()).resolve()
    #.resolve()把路径整理成绝对路径
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate #遍历父目录 找到项目的根目录
    return current

def default_workspace(root: Path | None = None) -> Path:
    return (root or find_project_root()) / ".Agent01" / "workspace"
    #定义工作区路径

