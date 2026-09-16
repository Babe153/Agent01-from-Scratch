#本质上是 CLI 的输出格式化器，不负责执行 Agent，只负责把 stream_agent_events() 持续 yield 出来的事件，整理成适合人阅读的终端输出
from __future__ import annotations

from typing import Any

import typer #Typer 主要用于制作命令行程序 在这个 formatter.py 中，Typer 没有负责定义命令，主要负责向终端输出内容

def safe_echo(message: Any = "", **kwargs: Any) -> None:
    # kwargs 是 keyword arguments（关键字参数）的缩写。 前面的两个星号 ** 表示：收集调用函数时额外传入的所有“参数名=参数值”，并保存成一个字典。
    # 接收消息及任意额外输出参数，并将这些参数原样转交给 typer.echo
    text = str(message)
    try:
        typer.echo(text, **kwargs) #尝试正常输出 调用typer.echo() 可以将text输出到终端
    except UnicodeEncodeError:
        safe = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        #.encode()先把字符串编码成 UTF-8 字节。如果遇到无法编码的异常字符，就使用替代字符代替
        #.decode()再把 UTF-8 字节解码回 Python 字符串。如果遇到无法解码的数据，同样使用替代字符。
        typer.echo(safe, **kwargs) #再次尝试输出

    
def safe_secho(message: Any = "", **kwargs: Any) -> None:
    #safe_secho() 和 safe_echo() 的逻辑完全一样，唯一区别是使用了 typer.secho()，因此可以设置终端文字的颜色和样式。typer.echo()：普通输出 typer.secho()：带样式输出，secho 可以理解为 styled echo
    text = str(message)
    try:
        typer.secho(text, **kwargs)
    except UnicodeEncodeError:
    3    safe = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        typer.secho(safe, **kwargs)

def _shorten(value: Any, limit: int = 260) -> str:
    #按照 Python 命名习惯，表示这是模块内部使用的辅助函数，不希望被其他模块当成主要接口使用。
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."#python

def print_event(event: dict[str, Any]) -> None:
    #真正的把agent输出的各类event打印出来
    event_type = event.get("type")
    if event_type == "workspace":
        #如果event是workspace 打印出路径
        safe_secho(f"workspace: {event['path']}", fg=typer.colors.BLUE)
        return

    if event_type != "agent_event":
        #如果event类型不是agent event 说明这个event或者有问题或者无价值 所以用shorten打印出一部分即可
        safe_echo(_shorten(event))
        return

    payload = event["event"] #把具体event赋值给payload
    if not isinstance(payload, dict):
        #如果这个event不是字典 就打印出一部分即可 因为或许异常或许无价值
        safe_echo(_shorten(payload))
        return

    for node, update in payload.items():
        #node update是自定义名称 代表langgraph的执行节点与节点更新的信息
        safe_secho(f"\n[{node}]", fg=typer.colors.CYAN) #打印出节点node名称 用青色
        messages = update.get("messages") if isinstance(update, dict) else None #获取update的messages信息 如果update不是字典(which means没有messages) 就赋值None
        if not messages:
            safe_echo(_shorten(update))
            continue #如果没有messages continue处理下个节点的信息
        for message in messages:
            tool_calls = getattr(message, "tool_calls", None) #拿到tool_calls全部信息 没有就是None
            name = getattr(message, "name", None) #拿到name全部信息 没有就是None
            content = getattr(message, "content", "") #拿到content全部信息 没有就是None

            if tool_calls: #如果拿到的是tool_calls
                for call in tool_calls:
                    safe_secho(f"tool call -> {call.get('name')}", fg=typer.colors.YELLOW)
                    safe_echo(_shorten(call.get("args", {}))) #打印出所有tool的名字和参数

            elif name: #如果拿到的是name 如果消息包含 name，通常说明它是某个工具返回的 ToolMessage
                safe_secho(f"tool result <- {name}", fg=typer.colors.GREEN)
                safe_echo(_shorten(content, 900)) #打印出name的名字 和内容 name通常表示“这条工具结果消息来自哪个工具” 内容通常是是否通过 content='{"ok": true, "content": "Hello"}'

            elif content: #如果拿到的是content (如果没有工具调用和工具名称，但包含文字内容)
                safe_echo(_shorten(content, 1200)) #可能是最终输出 因为没有toolcall内容 打印模型的文字回复，最多显示 1200 个字符