from __future__ import annotations

import json
from typing import Any

from rich import box #导入 Rich 提供的边框样式
from rich.console import Console # 导入 Console 类，它是 Rich 的终端输出接口
from rich.panel import Panel # 导入面板组件，用于给内容加上边框和标题
from rich.table import Table #导入表格组件，可以添加列和行
from rich.text import Text #导入带样式的文本组件

console = Console() #创建一个 Console 实例，命名为 console

STATUS_SYMBOLS = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "completed": "[x]",
    "blocked": "[!]",
}

STATUS_STYLES = {
    "pending": "dim",
    "in_progress": "bold yellow",
    "completed": "bold green",
    "blocked": "bold red",
}

def safe_echo(message: Any = "", **_: Any) -> None:
    #不主动指定样式
    console.print(str(message))

def safe_secho(message: Any = "", **kwargs: Any) -> None:
    #允许调用方传入颜色或样式
    color = kwargs.get("fg") or kwargs.get("style")
    console.print(str(message), style=color)

def _shorten(value: Any, limit: int = 260) -> str:
    #太长的信息可以不全部输出
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."

def print_event(event: dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "workspace":
        console.print(Panel(str(event["path"]), title="Workspace", border_style="blue", box=box.ROUNDED))
        return
    if event_type == "custom_event":
        print_custom_event(event["event"])
        return
    if event_type == "graph_event":
        print_graph_event(event["event"])
        return
    console.print(_shorten(event))

def print_custom_event(event: dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "plan_snapshot":
        render_plan(event, title=f"Plan Snapshot · {event.get('node', 'graph')}")
        return
    if event_type == "todo_update":
        render_plan(event, title="Todo Updated", border_style="yellow")
        return
    if event_type == "tool_call":
        console.print(
            Panel(
                _format_args(event.get("args", {})),
                title=f"Tool Call · {event.get('name')}",
                border_style="magenta",
                box=box.ROUNDED,
            )
        )
        return
    if event_type == "tool_result":
        result = event.get("result")
        style = "green"
        if isinstance(result, dict) and result.get("ok") is False:
            style = "red"
        console.print(
            Panel(
                _format_tool_result(result),
                title=f"Tool Result · {event.get('name')}",
                border_style=style,
                box=box.ROUNDED,
            )
        )
        return
    console.print(Panel(_shorten(event, 1000), title="Event", box=box.ROUNDED))

def print_graph_event(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        console.print(_shorten(payload))
        return

    for node, update in payload.items():
        if not isinstance(update, dict):
            console.print(Panel(_shorten(update), title=str(node), box=box.ROUNDED))
            continue
        if node == "planner":
            render_plan(update, title="Planner", border_style="cyan")
        elif node == "actor":
            summary = update.get("last_actor_summary")
            if summary:
                console.print(Panel(_shorten(summary, 1200), title="Actor Summary", border_style="cyan"))
        elif node == "verifier":
            render_verifier(update)
        elif node == "final":
            render_final(update)
        else:
            console.print(Panel(_shorten(update, 1200), title=str(node), box=box.ROUNDED))

def render_plan(update: dict[str, Any], *, title: str, border_style: str = "cyan") -> None:
    plan = update.get("plan_summary", "")
    todos = update.get("todos", [])
    commands = update.get("verification_commands", [])

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Todo")
    table.add_column("Note", style="dim")
    for todo in todos:
        status = todo.get("status", "pending")
        table.add_row(
            todo.get("id", ""),
            Text(STATUS_SYMBOLS.get(status, "[?]"), style=STATUS_STYLES.get(status, "")),
            todo.get("content", ""),
            todo.get("note", ""),
        )

    command_text = "\n".join(f"  - {command}" for command in commands)
    body = Table.grid(expand=True)
    if plan:
        body.add_row(Text(plan, style="bold"))
    if todos:
        body.add_row(table)
    if commands:
        body.add_row(Text("Verifier commands\n" + command_text, style="green"))
    console.print(Panel(body, title=title, border_style=border_style, box=box.ROUNDED))

def render_verifier(update: dict[str, Any]) -> None:
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("Command")
    table.add_column("Exit", justify="right")
    table.add_column("Status")
    table.add_column("Output")
    for result in update.get("verification_results", []):
        ok = bool(result.get("ok"))
        status = Text("PASS" if ok else "FAIL", style="bold green" if ok else "bold red")
        output = result.get("stdout") or result.get("stderr") or ""
        table.add_row(
            result.get("command", ""),
            str(result.get("exit_code")),
            status,
            _shorten(output, 240),
        )
    footer = f"passed={update.get('passed')} | attempts={update.get('attempts')}"
    panel_grid = Table.grid(expand=True)
    panel_grid.add_row(table)
    panel_grid.add_row(Text(footer, style="yellow"))
    console.print(Panel(panel_grid, title="Verifier", border_style="green" if update.get("passed") else "red"))

def render_final(update: dict[str, Any]) -> None:
    answer = update.get("final_answer", "")
    style = "green" if "PASSED" in answer else "red"
    console.print(Panel(_shorten(answer, 2000), title="Final", border_style=style, box=box.ROUNDED))

def _format_args(args: Any) -> str:
    return _shorten(args, 900)

def _format_tool_result(result: Any) -> str:
    if not isinstance(result, dict):
        return _shorten(result, 900)
    keys = ["ok", "type", "path", "exit_code", "timed_out", "duration_ms", "error"]
    lines = [f"{key}: {result[key]}" for key in keys if key in result]
    if "stdout" in result and result["stdout"]:
        lines.append("stdout:\n" + _shorten(result["stdout"], 500))
    if "stderr" in result and result["stderr"]:
        lines.append("stderr:\n" + _shorten(result["stderr"], 500))
    if "todos" in result:
        lines.append(f"todos: {len(result['todos'])} item(s)")
    if not lines:
        lines.append(_shorten(result, 900))
    return "\n".join(lines)