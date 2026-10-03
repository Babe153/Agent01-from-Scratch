from __future__ import annotations

from pathlib import Path

from Agent01.core.agent import create_runtime
from Agent01.core.paths import new_task_workspace


def test_new_task_workspace_is_unique(tmp_path: Path) -> None:
    first = new_task_workspace(tmp_path)
    second = new_task_workspace(tmp_path)

    assert first != second
    assert first.parent == tmp_path / ".Agent01" / "workspaces"
    assert first.name.startswith("workspace-")


def test_create_runtime_uses_fresh_default_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("Agent01.core.paths.find_project_root", lambda start=None: tmp_path)

    first = create_runtime()
    second = create_runtime()

    assert first.workspace != second.workspace
    assert first.workspace.exists()
    assert second.workspace.exists()


def test_create_runtime_respects_explicit_workspace(tmp_path: Path) -> None:
    explicit = tmp_path / "my-workspace"

    runtime = create_runtime(explicit)

    assert runtime.workspace == explicit
    assert explicit.exists()


def test_create_runtime_sets_approval_configuration(tmp_path: Path) -> None:
    handler = lambda request: True

    runtime = create_runtime(tmp_path / "workspace", approval_mode="deny", approval_handler=handler)

    assert runtime.approval_mode == "deny"
    assert runtime.approval_handler is handler


def test_create_runtime_reads_bash_harness_env(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "agent.env"
    monkeypatch.setenv("AGENT_BASH_DEFAULT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("AGENT_BASH_MAX_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("AGENT_BASH_MAX_OUTPUT_CHARS", "1234")
    monkeypatch.setenv("AGENT_BASH_ENV_FILE", str(env_file))

    runtime = create_runtime(tmp_path / "workspace")

    assert runtime.bash_default_timeout_seconds == 45
    assert runtime.bash_max_timeout_seconds == 300
    assert runtime.bash_max_output_chars == 1234
    assert runtime.bash_env_file == env_file


def test_create_runtime_sets_checkpoint_configuration(tmp_path: Path) -> None:
    resume = tmp_path / "workspace"

    runtime = create_runtime(resume, checkpoint_mode="strict", resume_from=resume)

    assert runtime.checkpoint_mode == "strict"
    assert runtime.resume_from == resume


def test_create_runtime_reads_checkpoint_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_CHECKPOINT_MODE", "deny-this-invalid-mode")

    runtime = create_runtime(tmp_path / "workspace", checkpoint_mode=None)

    assert runtime.checkpoint_mode == "light"


def test_stream_agent_events_saves_checkpoint_on_keyboard_interrupt(monkeypatch, tmp_path: Path) -> None:
    from Agent01.core.agent import stream_agent_events

    class FakeWorkflow:
        def stream(self, inputs, stream_mode):
            yield ("updates", {"planner": {"plan_summary": "plan", "messages": []}})
            raise KeyboardInterrupt

    monkeypatch.setattr("Agent01.core.agent.build_workflow", lambda: FakeWorkflow())

    events = list(
        stream_agent_events(
            "demo task",
            workspace=tmp_path,
            checkpoint_mode="light",
            approval_mode="deny",
        )
    )

    assert any(event.get("type") == "custom_event" and event["event"].get("type") == "checkpoint_saved" for event in events)
    assert (tmp_path / ".Agent01" / "checkpoints" / "RECOVERY.md").exists()
    assert "plan" in (tmp_path / ".Agent01" / "checkpoints" / "RECOVERY.md").read_text(encoding="utf-8")
