from __future__ import annotations

import json #import json 是为了让这个 Todo 工具能够看懂 Agent 传来的 JSON 字符串
from typing import Any
from Agent01.core.state import RuntimeState

VALID_TODO_STATUSES = {"pending", "in_progress", "completed", "blocked"} #合法状态
TODO_FILE = "TODO.md"

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

def persist_todos( #持久化todo
    state: RuntimeState,
    todos: list[dict[str, Any]],
    acceptance_criteria: list[str] | None = None,
    verification_commands: list[str] | None = None,
    plan_summary: str = "",
) -> dict[str, Any]:
    path = state.assert_workspace_path(state.workspace / TODO_FILE)
    content = render_todo_markdown(todos, acceptance_criteria or [], verification_commands or [], plan_summary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    state.record_read(path, complete=True)
    return {"ok": True, "path": TODO_FILE, "lines": len(content.splitlines()), "todos": todos}

def render_todo_markdown(
    todos: list[dict[str, Any]],
    acceptance_criteria: list[str],
    verification_commands: list[str],
    plan_summary: str = "",
) -> str:
    lines = ["# Agent01 Todo", ""]
    if plan_summary:
        lines.extend(["## Plan", "", plan_summary, ""])
    lines.extend(["## Todos", ""])
    if todos:
        for todo in todos:
            status = str(todo.get("status", "pending"))
            box = {"pending": " ", "in_progress": "-", "completed": "x", "blocked": "!"}.get(status, " ")
            note = str(todo.get("note", ""))
            note_text = f" — {note}" if note else ""
            lines.append(f"- [{box}] **{todo.get('id', '')}** `{status}` {todo.get('content', '')}{note_text}")
    else:
        lines.append("- [ ] No todos yet.")
    if acceptance_criteria:
        lines.extend(["", "## Acceptance Criteria", ""])
        lines.extend(f"- {item}" for item in acceptance_criteria)
    if verification_commands:
        lines.extend(["", "## Verification Commands", ""])
        lines.extend(f"- `{command}`" for command in verification_commands)
    lines.append("")
    return "\n".join(lines)