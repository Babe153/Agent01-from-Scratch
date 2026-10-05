from __future__ import annotations

from dataclasses import dataclass
from threading import Event

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from Agent01.core.approval import ApprovalDecision, ApprovalRequest

@dataclass
class ApprovalGate:
    request: ApprovalRequest
    decision: ApprovalDecision | None = None

    def __post_init__(self) -> None:
        """dataclass 生成的初始化方法结束后自动调用。
        创建未置位的线程 Event，作为“审批已有结果”的信号；
        它不同于 Agent 的事件字典，专门用于线程之间等待和唤醒。
        """
        self._ready = Event()

    def resolve(self, approved: bool) -> None:
        """接收界面传来的批准或拒绝结果，构造 ApprovalDecision。
        先保存决定，再调用 Event.set 唤醒等待线程，保证醒来后能够读到结果。
        拒绝时填写原因，供工具返回审批失败信息。
        """
        reason = "" if approved else "Rejected by human operator."
        self.decision = ApprovalDecision(approved=approved, reason=reason)
        self._ready.set()

    def wait(self) -> ApprovalDecision:
        """让调用它的工作线程等待审批信号，直到 resolve 设置 Event。
        等待结束后返回决定；若此时仍没有决定，则返回默认拒绝。
        此实现没有超时，也不会仅因窗口关闭而自动唤醒，必须有人设置该信号。
        """
        self._ready.wait()
        return self.decision or ApprovalDecision(approved=False, reason="Approval dialog closed.")


class ApprovalModal(ModalScreen[bool]):
    BINDINGS = [
        ("y", "approve", "Approve"),
        ("enter", "approve", "Approve"),
        ("n", "deny", "Deny"),
        ("escape", "deny", "Deny"),
    ]

    DEFAULT_CSS = """
    ApprovalModal {
        align: center middle;
    }

    ApprovalModal #approval-dialog {
        width: 74;
        max-width: 90%;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }

    ApprovalModal #approval-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    ApprovalModal #approval-command {
        border: tall $panel;
        padding: 1;
        margin: 1 0;
        max-height: 10;
    }

    ApprovalModal #approval-buttons {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, request: ApprovalRequest, workspace: str) -> None:
        """初始化模态窗口，并保存待审批请求和工作区文字。
        请求中包含工具名、命令与风险说明，后面的 compose 会将它们展示出来。
        """
        super().__init__()
        self.request = request
        self.workspace = workspace

    def compose(self) -> ComposeResult:
        """构造审批对话框：工具名、风险、工作区、命令和两个按钮。
        命令用 Rich Text 显示并允许换行；Button 的 id 用于判断批准还是拒绝。
        yield 交给 Textual 创建控件，不在此处执行命令。
        """
        with Container(id="approval-dialog"):
            yield Static(f"Human Approval · {self.request.tool_name}", id="approval-title")
            yield Static(f"Risk: {self.request.risk_reason}")
            yield Static(f"Workspace: {self.workspace}")
            yield Static(Text(self.request.command, overflow="fold"), id="approval-command")
            yield Static("Approve this command?  y/Enter = approve · n/Esc = deny")
            with Horizontal(id="approval-buttons"):
                yield Button("Approve", variant="success", id="approve")
                yield Button("Deny", variant="error", id="deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """用户点击按钮后由 Textual 调用。
        判断按钮 id 是否为 approve，将 True 或 False 传给 dismiss。
        dismiss 关闭弹窗，并把结果传给主界面注册的回调。
        """
        self.dismiss(event.button.id == "approve")

    def on_key(self, event: events.Key) -> None:
        """处理弹窗中的按键：y/Enter 批准，n/Escape 拒绝。
        通过 dismiss 返回布尔值，最终由主界面回调唤醒等待审批的工作线程。
        """
        if event.key in {"y", "enter"}:
            self.dismiss(True)
        elif event.key in {"n", "escape"}:
            self.dismiss(False)

    def action_approve(self) -> None:
        """供 BINDINGS 快捷键映射调用的批准动作。
        关闭弹窗并返回 True；它只给出审批决定，实际命令仍由后端工具执行。
        """
        self.dismiss(True)

    def action_deny(self) -> None:
        """供 BINDINGS 快捷键映射调用的拒绝动作。
        关闭弹窗并返回 False，让后端工具收到拒绝结果。
        """
        self.dismiss(False)
