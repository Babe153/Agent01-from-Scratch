from __future__ import annotations

import sys #Python 运行环境和系统交互的标准库
from pathlib import Path
from typing import Annotated, Literal #typing 是 Python 专门提供类型注解工具的标准库。 Annotated 的作用是： 在原本的类型信息上，再附加一些额外说明或配置。

import typer #Typer 是一个第三方命令行开发框架，用来把普通 Python 函数转换成命令行程序

from Agent01.cli.formatter import print_event, safe_echo, safe_secho
from rich import box
from rich.panel import Panel
from typer.core import TyperGroup

from Agent01.core.approval import ApprovalDecision, ApprovalRequest
from Agent01.core.agent import stream_agent_events

class Agent01Group(TyperGroup):
    """Let ``Agent01 "task"`` coexist with real subcommands."""

    def parse_args(self, ctx, args):  # type: ignore[no-untyped-def]
        #区分自然语言任务与 tui 子命令；任务文字暂存到 ctx.obj，交给 main 读取。
        commands = set(self.commands)
        remaining: list[str] = []
        task_parts: list[str] = []
        index = 0
        while index < len(args):
            arg = args[index]
            if arg in commands or arg == "--help":
                remaining.extend(args[index:])
                break
            if arg.startswith("-"):
                remaining.append(arg)
                if "=" not in arg and index + 1 < len(args) and not args[index + 1].startswith("-"):
                    remaining.append(args[index + 1])
                    index += 2
                    continue
                index += 1
                continue
            task_parts.extend(args[index:])
            break
        if task_parts:
            ctx.obj = dict(ctx.obj or {})
            ctx.obj["task_arg"] = " ".join(task_parts)
        return super().parse_args(ctx, remaining)


app = typer.Typer(
    cls=Agent01Group,
    help='Agent01: a teaching-first mini CodeAgent. Use `Agent01 "task"` for Rich output or `Agent01 tui` for Textual TUI.',
)

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
    #task：用户输入的自然语言任务 = None表示表示用户不提供任务时 task = None
    #本阶段改由自定义参数解析器读取任务，见下面的 ctx.obj。
    workspace: Annotated[ #类型、Typer 配置、默认值三部分构成
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace for generated files. Defaults to a fresh .Agent01/workspaces/workspace-* directory."),
    ] = None,
    max_attempts: Annotated[
        int,
        typer.Option("--max-attempts", help="Maximum planner/actor/verifier attempts before finalizing."),
    ] = 3,
    approval_mode: Annotated[
        Literal["inline", "auto", "deny"],
        typer.Option("--approval-mode", help="Human approval mode for high-risk BashTool commands: inline, auto, or deny."),
    ] = "inline",
    #新增：选择保存模式；通过 --resume 指定已有工作区继续任务。
    checkpoint_mode: Annotated[
        Literal["light", "strict", "off"],
        typer.Option("--checkpoint-mode", help="Checkpoint mode: light, strict, or off."),
    ] = "light",
    #Trace 与 Checkpoint 独立开关，控制是否记录运行过程。
    trace_mode: Annotated[
        Literal["on", "off"],
        typer.Option("--trace-mode", help="Trace logging mode: on or off."),
    ] = "on",
    resume: Annotated[
        Path | None,
        typer.Option("--resume", help="Resume from an existing Agent01 workspace."),
    ] = None,
) -> None:
    if ctx.invoked_subcommand is not None: #ctx.invoked_subcommand 表示用户是否调用了某个子命令
        return
    configure_console()
    task = None
    if isinstance(ctx.obj, dict):
        task = ctx.obj.get("task_arg")
    #恢复时可以不重复输入任务，原任务会从 checkpoint 中读取。
    if not task and resume is None:
        safe_echo(ctx.get_help())
        raise typer.Exit()

    safe_secho("Agent01 version 5: MultiAgent + context/harness engineering", fg=typer.colors.MAGENTA) #前面代码都没执行 到这里准备唤醒agent
    approval_handler = _inline_approval_handler if approval_mode == "inline" else None
    for event in stream_agent_events(
        task,
        workspace=workspace,
        max_attempts=max_attempts,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_workspace=resume,
        trace_mode=trace_mode,
    ):
        #event 接收每次 yield 出来的事件 每当 stream_agent_events() 执行一次： yield 某个事件 这个事件就会赋给：event
        print_event(event) #formatter里面那个方法 真正接收event然后打印出来


@app.command("tui")
def tui(
    task: Annotated[str | None, typer.Argument(help="Optional initial task for the Textual TUI.")] = None,
    max_attempts: Annotated[
        int,
        typer.Option("--max-attempts", help="Maximum planner/actor/verifier attempts before finalizing."),
    ] = 3,
    approval_mode: Annotated[
        Literal["inline", "auto", "deny"],
        typer.Option("--approval-mode", help="Human approval mode for high-risk BashTool commands: inline, auto, or deny."),
    ] = "inline",
    checkpoint_mode: Annotated[
        Literal["light", "strict", "off"],
        typer.Option("--checkpoint-mode", help="Checkpoint mode: light, strict, or off."),
    ] = "light",
    trace_mode: Annotated[
        Literal["on", "off"],
        typer.Option("--trace-mode", help="Trace logging mode: on or off."),
    ] = "on",
    resume: Annotated[
        Path | None,
        typer.Option("--resume", help="Resume from an existing Agent01 workspace."),
    ] = None,
) -> None:
    """Open the Textual terminal interface."""
    #仅在打开 TUI 时导入界面类，普通命令行运行仍使用原来的 formatter。
    configure_console()
    from Agent01.cli.tui import Agent01TuiApp

    Agent01TuiApp(
        initial_task=task,
        max_attempts=max_attempts,
        approval_mode=approval_mode,
        checkpoint_mode=checkpoint_mode,
        trace_mode=trace_mode,
        resume=resume,
    ).run()


def _inline_approval_handler(request: ApprovalRequest) -> ApprovalDecision:
    from Agent01.cli.formatter import console

    console.print(
        Panel(
            f"Command:\n{request.command}\n\nRisk:\n{request.risk_reason}",
            title=f"Human Approval · {request.tool_name}",
            border_style="yellow",
            box=box.ROUNDED,
        )
    )
    answer = typer.prompt("Approve? [y/N]", default="n", show_default=False).strip().lower()
    console.print() #新增：审批回答后留一行空白，避免后续输出挤在一起
    approved = answer in {"y", "yes"}
    return ApprovalDecision(approved=approved, reason="" if approved else "Rejected by human operator.")
