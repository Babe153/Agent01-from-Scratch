from __future__ import annotations

import sys #Python 运行环境和系统交互的标准库
from pathlib import Path
from typing import Annotated #typing 是 Python 专门提供类型注解工具的标准库。 Annotated 的作用是： 在原本的类型信息上，再附加一些额外说明或配置。

import typer #Typer 是一个第三方命令行开发框架，用来把普通 Python 函数转换成命令行程序

from Agent01.cli.formatter import print_event, safe_echo, safe_secho
from Agent01.core.agent import stream_agent_events

app = typer.Typer(help="Agent01: a mini CodeAgent.")
#app = 一个命令行程序 其中的 help 是整个命令行程序的介绍。用户执行: Agent01 --help 就会看到类似：Agent01: a mini CodeAgent.

def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr): #sys.stdout 和 sys.stderr 是程序最终把文字发送到命令行终端的两个通道。
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace") #提前规定：之后通过 stdout 和 stderr 输出的文本，都使用 UTF-8 编码
'''
Agent 产生事件
    ↓
print_event(event) 判断事件类型并格式化
    ↓
safe_echo() / safe_secho() 输出文字
    ↓
sys.stdout 或 sys.stderr
    ↓
命令行终端显示
'''

#这是一个装饰器，把下面的 main() 注册到 app 这个 Typer 命令行应用中
@app.callback(invoke_without_command=True) #invoke_without_command=True表示: 即使用户没有输入子命令，也执行 main()
def main(
    ctx: typer.Context, #Typer 的命令行上下文
    #类型、Typer 配置、默认值三部分构成
    task: Annotated[str | None, typer.Argument(help="Natural-language task for the CodeAgent.")] = None, #task：用户输入的自然语言任务 = None表示表示用户不提供任务时 task = None
    workspace: Annotated[ #类型、Typer 配置、默认值三部分构成
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace for generated files. Defaults to .Agent01/workspace."),
    ] = None,
    max_attempts: Annotated[
        int,
        typer.Option("--max-attempts", help="Maximum planner/actor/verifier attempts before finalizing."),
    ] = 3,
) -> None:
    if ctx.invoked_subcommand is not None: #ctx.invoked_subcommand 表示用户是否调用了某个子命令
        return
    configure_console()
    if not task:
        safe_echo(ctx.get_help())
        raise typer.Exit()

    safe_secho("Agent01 version 2: LangGraph planner -> actor -> verifier", fg=typer.colors.MAGENTA) #前面代码都没执行 到这里准备唤醒agent
    for event in stream_agent_events(task, workspace=workspace, max_attempts=max_attempts):
        #event 接收每次 yield 出来的事件 每当 stream_agent_events() 执行一次： yield 某个事件 这个事件就会赋给：event
        print_event(event) #formatter里面那个方法 真正接收event然后打印出来