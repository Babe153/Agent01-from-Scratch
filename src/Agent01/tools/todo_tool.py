from __future__ import annotations

import json #import json 是为了让这个 Todo 工具能够看懂 Agent 传来的 JSON 字符串
from typing import Any

VALID_TODO_STATUSES = {"pending", "in_progress", "completed", "blocked"} #合法状态

def _normalize_items(items: Any) -> list[str]:
    #不管 Agent 传进来的是字符串、JSON 字符串、字典、列表还是数字，都尽量将其统一整理成 list[str]
    if isinstance(items, str): #传入字符串
        stripped = items.strip() #使用字符串的 strip() 方法，删除字符串开头和结尾的空白字符
        if not stripped: #如果是空字符串 返回空列表 防止其进入todo列表
            return []
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return [line.strip("- ").strip() for line in stripped.splitlines() if line.strip()]
        return _normalize_items(decoded) #递归调用自己 json.loads() 只负责解析 JSON，而 _normalize_items() 继续负责把解析结果统一整理成 list[str]。
    
    if isinstance(items, dict): #传入字典
        value = items.get("content") or items.get("title") or items.get("text") or items.get("command")
        return [str(value).strip()] if value else []
    
    if isinstance(items, list): #传入列表
        normalized: list[str] = [] #初始化一个列表normalized用于存储处理完的字符串
        for item in items: #遍历列表中的元素
            normalized.extend(_normalize_items(item)) #加入递归调用后的结果 清洗掉list里的其他数据类型
        return [item for item in normalized if item] #过滤掉列表里的空值（其实前面已经过滤了几次 这里算是个最后一道保险
    return [str(items).strip()] if items is not None and str(items).strip() else [] 


def write_todos(
    todos: list[str],
    acceptance_criteria: list[str],
    verification_commands: list[str],
) -> dict[str, Any]:
    cleaned_todos = _normalize_items(todos)
    cleaned_criteria = _normalize_items(acceptance_criteria)
    cleaned_commands = _normalize_items(verification_commands)

    return {
        "ok": bool(cleaned_todos and cleaned_criteria and cleaned_commands),
        "todos": cleaned_todos,
        "acceptance_criteria": cleaned_criteria,
        "verification_commands": cleaned_commands,
    }

def update_todo(
    todos: list[dict[str, str]],
    todo_id: str,
    status: str,
    note: str = "",
) -> dict[str, Any]:
    if status not in VALID_TODO_STATUSES:
        return {
            "ok": False,
            "error": f"status must be one of: {', '.join(sorted(VALID_TODO_STATUSES))}",
            "todos": todos,
        }

    updated: list[dict[str, str]] = []
    found = False
    for todo in todos:
        item = dict(todo)
        if item.get("id") == todo_id:
            item["status"] = status
            item["note"] = note
            found = True
        updated.append(item)

    if not found:
        return {"ok": False, "error": f"unknown todo_id: {todo_id}", "todos": todos}
    return {"ok": True, "todo_id": todo_id, "status": status, "note": note, "todos": updated}