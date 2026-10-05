from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable, Literal

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Footer, Header, Input, RichLog, Static

from Agent01.cli.event_summary import EventSummary, shorten, summarize_event
from Agent01.cli.tui.approval import ApprovalGate, ApprovalModal
from Agent01.cli.tui.logo import render_logo
from Agent01.core.approval import ApprovalDecision, ApprovalRequest
from Agent01.core.agent import stream_session_events
from Agent01.core.paths import default_workspace


StreamFactory = Callable[..., Iterable[dict[str, Any]]]


class AgentEventMessage(Message):
    def __init__(self, event: dict[str, Any]) -> None:
        """将后端的一条事件字典包装成 Textual 消息。
        先初始化 Message 基类，再保留原始 event；后台线程投递此消息后，
        界面线程通过 on_agent_event_message 读取它，不直接跨线程修改控件。
        """
        super().__init__()
        self.event = event


class RunFinishedMessage(Message):
    def __init__(self, status: str) -> None:
        """包装一次后台任务结束的状态字符串。
        status 可以是 finished、interrupted 或 failed；界面收到消息后恢复输入框。
        这里的 finished 表示事件流结束，并不等于任务一定通过验收。
        """
        super().__init__()
        self.status = status


class ApprovalRequestedMessage(Message):
    def __init__(self, gate: ApprovalGate) -> None:
        """包装审批请求与等待结果的 ApprovalGate 对象。
        界面和后台持有同一个 gate：界面填写决定，后台等待决定后继续执行。
        """
        super().__init__()
        self.gate = gate

class Agent01TuiApp(App[None]):
    CSS = """
    Screen {
        background: $surface;
    }

    #root {
        height: 1fr;
    }

    #top {
        height: 13;
        border-bottom: solid $primary;
        padding: 0 1;
    }

    #logo {
        width: 44;
        height: 12;
        content-align: center middle;
    }

    #title-block {
        width: 1fr;
        height: 12;
        padding-left: 1;
    }

    #title {
        text-style: bold;
        color: $primary;
    }

    #status {
        color: $text-muted;
    }

    #body {
        height: 1fr;
    }

    #events {
        width: 1fr;
        height: 100%;
        border-right: solid $panel;
    }

    #sidebar {
        width: 34;
        min-width: 28;
        height: 100%;
        padding: 1;
    }

    #side-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #input-row {
        height: 3;
        border: round $primary;
        padding: 0 1;
    }

    #prompt {
        width: 3;
        height: 1;
        content-align: center middle;
        color: $primary;
        text-style: bold;
    }

    #task-input {
        width: 1fr;
        height: 1;
        border: none;
        background: $surface;
    }

    #hint {
        color: $text-muted;
        width: 30;
        height: 1;
        padding-left: 1;
        content-align: right middle;
    }
    """

    BINDINGS = [
        ("ctrl+c", "cancel_or_quit", "Cancel/Quit"),
        ("ctrl+l", "clear_events", "Clear"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        initial_task: str | None = None,
        workspace: Path | None = None,
        max_attempts: int = 3,
        approval_mode: Literal["inline", "auto", "deny"] = "inline",
        checkpoint_mode: Literal["light", "strict", "off"] = "light",
        trace_mode: Literal["on", "off"] = "on",
        resume: Path | None = None,
        stream_factory: StreamFactory = stream_session_events,
    ) -> None:
        """保存启动参数，初始化界面使用的状态和计数器，此时还不执行 Agent。
        stream_factory 是可替换的事件流函数，默认使用 stream_session_events；
        测试时可传入假事件流，因此不需要调用模型。workspace/resume 决定工作区，
        running 防止重复启动，Lock 用于保护状态更新。控件由后面的 compose 创建。
        """
        super().__init__()
        self.initial_task = initial_task
        #一次 TUI 会话选定一个工作区，后续提交持续复用；/new 才换目录。
        self.workspace = resume or workspace or default_workspace()
        self.session_workspace = self.workspace
        self.max_attempts = max_attempts
        self.approval_mode = approval_mode
        self.checkpoint_mode = checkpoint_mode
        self.trace_mode = trace_mode
        self.resume = resume
        self.stream_factory = stream_factory
        self.running = False
        self.run_count = 0
        self.approval_count = 0
        self.failed_tool_count = 0
        self.tool_count = 0
        self.latest_workspace = str(self.session_workspace)
        self.latest_checkpoint = ""
        self.latest_trace = ""
        self.session_id = ""
        self.session_turn = 0
        self.last_route = ""
        self.sidebar_text = ""
        self.todos: list[dict[str, Any]] = []
        self._state_lock = Lock()

    def compose(self) -> ComposeResult:
        """由 Textual 调用，声明界面控件的层级和排列顺序。
        yield 把控件交给框架；with Vertical/Horizontal 指定纵向或横向容器。
        界面包括顶部 Logo、事件日志、运行状态侧栏、任务输入框和快捷键栏。
        id 用于 CSS 定位和 query_one 查找；这里只创建界面，不运行任务。
        """
        yield Header(show_clock=True)
        with Vertical(id="root"):
            with Horizontal(id="top"):
                #放大到 12 行字符，并同步增加顶部高度，保留更多 Logo 细节。
                yield Static(render_logo(max_width=42, max_rows=12), id="logo")
                with Vertical(id="title-block"):
                    yield Static("Agent01 TUI", id="title")
                    yield Static("ready", id="status")
                    yield Static("MultiAgent + Context/Harness Engineering", id="subtitle")
            with Horizontal(id="body"):
                yield RichLog(id="events", wrap=True, highlight=True, markup=True)
                with Vertical(id="sidebar"):
                    yield Static("Run State", id="side-title")
                    yield Static("", id="side-state")
            with Horizontal(id="input-row"):
                yield Static("❯", id="prompt")
                yield Input(placeholder="Chat or ask for coding work, then press Enter", id="task-input")
                yield Static("Enter send · /new session · Ctrl+L clear", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        """控件挂载完成后由框架调用，此时可以安全查找并更新控件。
        写入欢迎语、刷新侧栏并让输入框获得焦点；若有 initial_task，
        通过 call_after_refresh 等待首轮刷新后再启动。此版本仅传 resume
        而不传 initial_task 时不会自动运行恢复任务。
        """
        self._write_welcome()
        self._refresh_sidebar()
        self.query_one("#task-input", Input).focus()
        if self.initial_task:
            self.call_after_refresh(self.start_task, self.initial_task, self.resume)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """用户在输入框按 Enter 时调用，event 带有输入框和输入内容。
        只处理 task-input，忽略空白任务以及运行中的重复提交。
        清空输入框后启动新一轮；/new 切换会话，其余输入复用当前工作区。
        传入 None 仅表示不加载 checkpoint，不表示创建新的工作区。
        """
        if event.input.id != "task-input":
            return
        task = event.value.strip()
        if not task or self.running:
            return
        event.input.value = ""
        #本地界面命令不发送给模型。
        if task == "/new":
            self.start_new_session()
            return
        self.start_task(task, None)

    def on_agent_event_message(self, message: AgentEventMessage) -> None:
        """在界面线程接收后台投递的 AgentEventMessage。
        取出原始事件并交给 _handle_event，统一更新统计、日志和侧栏。
        """
        self._handle_event(message.event)

    def on_run_finished_message(self, message: RunFinishedMessage) -> None:
        """后台事件流结束后在界面线程收尾。
        解除 running 标记、清除恢复路径、重新启用并聚焦输入框，
        显示结束状态并刷新侧栏，让用户能够继续提交下一项任务。
        """
        self.running = False
        self.resume = None
        self.query_one("#task-input", Input).disabled = False
        self.query_one("#task-input", Input).focus()
        self.query_one("#status", Static).update(f"{message.status}; ready for next task")
        self._refresh_sidebar()

    def on_approval_requested_message(self, message: ApprovalRequestedMessage) -> None:
        """收到审批消息时创建并显示模态审批窗口。
        窗口显示命令、风险和工作区；push_screen 的第二个参数是关闭回调，
        由 _resolve_approval 生成，负责把用户选择送回同一个 gate。
        """
        workspace = self.latest_workspace or str(self.workspace or "")
        self.push_screen(ApprovalModal(message.gate.request, workspace), self._resolve_approval(message.gate))

    def action_cancel_or_quit(self) -> None:
        """处理 Ctrl+C 快捷键。空闲时退出，运行中只显示提示并返回。
        注意：这个版本并没有在这里取消后台线程，也没有主动保存新的 checkpoint；
        退出后可恢复的进度取决于后端此前实际写入的 checkpoint。
        """
        if self.running:
            self.notify("A run is active. Press Ctrl+Q to quit and let checkpoint handle recovery.", severity="warning")
            return
        self.exit()

    def action_clear_events(self) -> None:
        """处理清屏快捷键：清空 RichLog，再写入欢迎信息。
        仅改变日志区显示，不删除磁盘上的 Trace、Checkpoint 或任务文件。
        """
        self.query_one("#events", RichLog).clear()
        self._write_welcome()

    def start_task(self, task: str, resume: Path | None = None) -> None:
        """开始一项任务前设置界面状态，并把实际工作交给后台线程。
        防止并发提交，递增运行次数，清空本轮 TODO 和工具计数，保留同一会话上轮的日志路径，
        禁用输入框并显示任务说明。审批计数在此版本中不会逐任务重置。
        run_worker(thread=True) 执行 _run_stream，避免模型请求阻塞界面事件循环。
        """
        if self.running:
            self.notify("Agent01 is already running a task.", severity="warning")
            return
        self.running = True
        self.run_count += 1
        self.todos = []
        self.failed_tool_count = 0
        self.tool_count = 0
        self.query_one("#task-input", Input).disabled = True
        self.query_one("#status", Static).update("running")
        self._refresh_sidebar()
        self._write_run_start(task, resume)
        self.run_worker(lambda: self._run_stream(task, resume), thread=True, exclusive=False, name=f"Agent01-run-{self.run_count}")

    def _run_stream(self, task: str, resume: Path | None) -> None:
        """在工作线程中遍历后端事件流，并传递工作区和各项运行配置。
        每收到事件，使用 call_from_thread 将消息投递操作交回界面线程；
        不要在这个方法里直接修改 Textual 控件。发生普通异常时发送错误事件，
        finally 尝试发送结束消息。底层若已自行处理中断，这里未必收到 KeyboardInterrupt。
        """
        status = "finished"
        try:
            approval_handler = self._approval_handler if self.approval_mode == "inline" else None
            for event in self.stream_factory(
                task,
                session_workspace=self.session_workspace,
                max_attempts=self.max_attempts,
                approval_mode=self.approval_mode,
                approval_handler=approval_handler,
                checkpoint_mode=self.checkpoint_mode,
                resume_workspace=resume,
                trace_mode=self.trace_mode,
            ):
                self.call_from_thread(self.post_message, AgentEventMessage(event))
        except KeyboardInterrupt:
            status = "interrupted"
        except Exception as exc:
            status = "failed"
            error_event = {"type": "custom_event", "event": {"type": "tui_error", "error": f"{type(exc).__name__}: {exc}"}}
            self.call_from_thread(self.post_message, AgentEventMessage(error_event))
        finally:
            self.call_from_thread(self.post_message, RunFinishedMessage(status))

    def _approval_handler(self, request: ApprovalRequest) -> ApprovalDecision:
        """供后端工具调用的审批回调，在工作线程中运行。
        创建 gate，通知界面弹窗，然后 gate.wait 阻塞当前工作线程，
        直到用户决定。界面线程没有被阻塞，仍能处理按钮和键盘事件。
        """
        gate = ApprovalGate(request)
        self.call_from_thread(self.post_message, ApprovalRequestedMessage(gate))
        return gate.wait()

    def _resolve_approval(self, gate: ApprovalGate) -> Callable[[bool | None], None]:
        """生成弹窗关闭时使用的回调函数，而不是立刻执行审批。
        内部函数形成闭包，记住传入的 gate；返回的函数稍后接收弹窗结果，
        因此能够把决定送回对应的那次审批请求。
        """
        def resolve(result: bool | None) -> None:
            """在弹窗关闭时接收结果，转为布尔值；None 按拒绝处理。
            调用 gate.resolve 保存决定并唤醒工作线程，然后刷新侧栏显示。
            """
            approved = bool(result)
            gate.resolve(approved)
            self._refresh_sidebar()

        return resolve

    def _handle_event(self, event: dict[str, Any]) -> None:
        """处理一条后端事件的统一入口。
        先更新界面保存的状态，再用 summarize_event 转成显示摘要，
        将摘要写入日志区，最后刷新侧栏；它不修改 LangGraph 的任务 state。
        """
        self._update_state_from_event(event)
        summary = summarize_event(event)
        self._write_summary(summary)
        self._refresh_sidebar()

    def _update_state_from_event(self, event: dict[str, Any]) -> None:
        """拆开不同事件的外层包装，提取用于侧栏的状态。
        workspace 事件直接更新目录；graph_event 遍历各节点的更新字典；
        custom_event 直接处理内部 payload。with Lock 在退出时自动释放锁。
        """
        with self._state_lock:
            if event.get("type") == "workspace":
                self.latest_workspace = str(event.get("path", ""))
                self.session_workspace = Path(self.latest_workspace)
                return
            payload = event.get("event")
            if event.get("type") == "graph_event" and isinstance(payload, dict):
                for update in payload.values():
                    if isinstance(update, dict):
                        self._update_from_payload(update)
            elif event.get("type") == "custom_event" and isinstance(payload, dict):
                self._update_from_payload(payload)

    def _update_from_payload(self, payload: dict[str, Any]) -> None:
        """从节点更新或自定义事件中提取 TODO、工具次数和日志路径。
        工具结果 ok=False 时计入失败，requires_approval 为真时增加审批计数。
        Checkpoint 与 Trace 事件更新对应路径；未涉及的字段保持不变。
        """
        if isinstance(payload.get("todos"), list):
            self.todos = payload["todos"]
        if payload.get("type") == "tool_call":
            self.tool_count += 1
        if payload.get("type") == "tool_result":
            result = payload.get("result")
            if isinstance(result, dict):
                if result.get("ok") is False:
                    self.failed_tool_count += 1
                if result.get("requires_approval"):
                    self.approval_count += 1
        if payload.get("type") == "checkpoint_saved":
            self.latest_checkpoint = str(payload.get("path", ""))
        if payload.get("type") == "trace_summary":
            self.latest_trace = str(payload.get("trace_dir", ""))
        #保存后端事件里的会话信息，用于侧栏显示，不在界面直接写 session.json。
        if payload.get("type") == "session_started":
            self.session_id = str(payload.get("session_id", ""))
            self.session_turn = int(payload.get("turn_index", 0) or 0)
            self.latest_workspace = str(payload.get("workspace", self.latest_workspace))
        if payload.get("type") == "session_turn_started":
            self.session_turn = int(payload.get("turn", self.session_turn) or self.session_turn)
        if payload.get("type") == "session_turn_saved":
            self.session_turn = int(payload.get("turn", self.session_turn) or self.session_turn)
            self.last_route = str(payload.get("route", self.last_route))

    def _write_welcome(self) -> None:
        """查找事件日志控件，追加一块欢迎面板。
        启动界面和清屏后都会调用，说明输入任务即可开始，使用 /new 才切换会话工作区。
        """
        log = self.query_one("#events", RichLog)
        log.write(
            Panel(
                "Enter a message to start a persistent coding session. Use /new to open a fresh workspace.",
                title="Agent01",
                border_style="cyan",
            )
        )

    def _write_run_start(self, task: str, resume: Path | None) -> None:
        """在日志区标记新一轮任务的开始。
        将任务文字截断到显示上限，附上新任务或恢复任务的信息，
        使用运行次数作为面板标题，便于区分连续提交的任务。
        """
        mode = f"resume: {resume}" if resume is not None else f"session workspace: {self.session_workspace}"
        self.query_one("#events", RichLog).write(
            Panel(shorten(task, 1000) + f"\n\n{mode}", title=f"Turn {self.run_count}", border_style="magenta")
        )

    def _write_summary(self, summary: EventSummary) -> None:
        """把 EventSummary 转换成 Rich Panel 并追加到日志。
        标题、正文和边框颜色都来自摘要；正文为空时使用空格，保证面板可显示。
        """
        self.query_one("#events", RichLog).write(
            Panel(summary.body or " ", title=summary.title, border_style=summary.style)
        )

    def _refresh_sidebar(self) -> None:
        """读取当前界面状态，重新绘制侧栏的两列表格。
        展示运行状态、工作区、Checkpoint、Trace、工具和审批计数、TODO 概况。
        较长路径只在显示时截短，原始路径不变；sidebar_text 保留文本版本供测试检查。
        """
        status = "running" if self.running else "ready"
        workspace = shorten(self.latest_workspace or str(self.session_workspace), 80)
        checkpoint = shorten(self.latest_checkpoint or "(waiting)", 80)
        trace = shorten(self.latest_trace or "(waiting)", 80)
        tools = f"{self.tool_count} total / {self.failed_tool_count} failed"
        approvals = str(self.approval_count)
        todos = self._todo_sidebar_text()
        self.sidebar_text = "\n".join(
            [
                f"status {status}",
                f"turns {self.run_count}",
                f"session {self.session_id}",
                f"route {self.last_route or '(none)'}",
                f"workspace {workspace}",
                f"checkpoint {checkpoint}",
                f"trace {trace}",
                f"tools {tools}",
                f"approvals {approvals}",
                f"todos {todos}",
            ]
        )
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        table.add_row("status", status)
        table.add_row("turns", str(self.run_count))
        table.add_row("session", shorten(self.session_id or "(starting)", 24))
        table.add_row("route", self.last_route or "(none)")
        table.add_row("workspace", workspace)
        table.add_row("checkpoint", checkpoint)
        table.add_row("trace", trace)
        table.add_row("tools", tools)
        table.add_row("approvals", approvals)
        table.add_row("todos", todos)
        self.query_one("#side-state", Static).update(table)

    def _todo_sidebar_text(self) -> str:
        """将 TODO 列表汇总为适合侧栏显示的短文本。
        按 status 统计数量，并找到第一项 in_progress 显示其内容。
        next(..., None) 表示找不到时返回 None；没有 TODO 时返回占位提示。
        """
        if not self.todos:
            return "(none yet)"
        counts: dict[str, int] = {}
        for todo in self.todos:
            status = str(todo.get("status", "pending"))
            counts[status] = counts.get(status, 0) + 1
        current = next((todo for todo in self.todos if todo.get("status") == "in_progress"), None)
        count_text = ", ".join(f"{key}:{value}" for key, value in sorted(counts.items()))
        if current:
            return f"{count_text}\n{shorten(current.get('content', current.get('description', '')), 120)}"
        return count_text

    def start_new_session(self) -> None:
        """处理 /new：空闲时选择新工作区，并清空会话 ID、路由和侧栏统计。
        不会删除旧工作区或其 session.json；旧记录仍可通过指定原路径继续使用。
        run_count 在本版本没有重置，侧栏 turns 是本次 TUI 启动以来提交的次数。
        """
        if self.running:
            self.notify("Agent01 is already running a task.", severity="warning")
            return
        self.workspace = default_workspace()
        self.session_workspace = self.workspace
        self.resume = None
        self.latest_workspace = str(self.session_workspace)
        self.latest_checkpoint = ""
        self.latest_trace = ""
        self.session_id = ""
        self.session_turn = 0
        self.last_route = ""
        self.todos = []
        self.failed_tool_count = 0
        self.tool_count = 0
        self.approval_count = 0
        self._refresh_sidebar()
        self.query_one("#events", RichLog).write(
            Panel(str(self.session_workspace), title="New Session", border_style="cyan")
        )
