from __future__ import annotations

from Agent01.cli.formatter import (
    render_checkpoint_resumed,
    render_checkpoint_saved,
    render_context_compression,
    render_context_monitor,
    render_memory_snapshot,
    render_plan,
    render_sources,
    render_verifier,
)


def test_render_plan_handles_todo_table(capsys) -> None:
    render_plan(
        {
            "plan_summary": "demo plan",
            "todos": [
                {"id": "todo-1", "content": "write tests", "status": "completed", "note": "done"},
                {"id": "todo-2", "content": "implement", "status": "in_progress", "note": ""},
            ],
            "verification_commands": ["python -m pytest -q"],
        },
        title="Test Plan",
    )

    output = capsys.readouterr().out
    assert "demo plan" in output
    assert "todo-1" in output
    assert "python -m pytest -q" in output


def test_render_sources_handles_source_table(capsys) -> None:
    render_sources(
        [{"title": "Amiya", "url": "https://example.com/amiya", "content": "Arknights character"}],
        title="searchAgent",
        answer="Amiya summary",
    )

    output = capsys.readouterr().out
    assert "Amiya summary" in output
    assert "https://example.com/amiya" in output


def test_render_verifier_handles_model_checks(capsys) -> None:
    render_verifier(
        {
            "passed": True,
            "attempts": 1,
            "verifier_summary": "looks good",
            "verification_checks": [{"name": "html", "passed": True, "detail": "file exists"}],
        }
    )

    output = capsys.readouterr().out
    assert "looks good" in output
    assert "html" in output


def test_render_context_monitor(capsys) -> None:
    render_context_monitor(
        {
            "context_token_count": 120,
            "context_token_limit": 100,
            "context_should_compress": True,
            "context_next_node": "verifier",
        }
    )

    output = capsys.readouterr().out
    assert "120" in output
    assert "verifier" in output


def test_render_context_compression(capsys) -> None:
    render_context_compression(
        {
            "compression_events": [
                {
                    "before_tokens": 1000,
                    "after_tokens": 80,
                    "removed_messages": 12,
                    "next_node": "planner",
                    "summary": "compressed",
                }
            ]
        }
    )

    output = capsys.readouterr().out
    assert "1000" in output
    assert "compressed" in output


def test_tool_result_formats_notepad_content(capsys) -> None:
    from Agent01.cli.formatter import print_custom_event

    print_custom_event(
        {
            "type": "tool_result",
            "node": "codeAgent",
            "name": "NotepadReadTool",
            "result": {"ok": True, "path": "NOTEPAD.md", "content": "Important note"},
        }
    )

    output = capsys.readouterr().out
    assert "Important note" in output


def test_render_memory_snapshot(capsys) -> None:
    render_memory_snapshot(
        {
            "node": "planner",
            "rules_count": 5,
            "todo_count": 2,
            "source_count": 1,
            "handoff_count": 1,
            "notepad_exists": True,
            "history_exists": False,
            "history_path": "HISTORY_SUMMARY.md",
            "layers": {
                "rules": "workspace rules",
                "working_memory": "task and todos",
                "history_summary_store": "notepad and summary",
            },
        }
    )

    output = capsys.readouterr().out
    assert "Memory Snapshot" in output
    assert "working_memory" in output
    assert "HISTORY_SUMMARY.md" in output


def test_print_custom_event_handles_memory_snapshot(capsys) -> None:
    from Agent01.cli.formatter import print_custom_event

    print_custom_event(
        {
            "type": "memory_snapshot",
            "node": "verifier",
            "rules_count": 5,
            "todo_count": 1,
            "source_count": 0,
            "handoff_count": 0,
            "notepad_exists": False,
            "history_exists": True,
            "history_path": "HISTORY_SUMMARY.md",
            "layers": {
                "rules": "rules",
                "working_memory": "work",
                "history_summary_store": "history",
            },
        }
    )

    output = capsys.readouterr().out
    assert "Memory Snapshot" in output
    assert "verifier" in output


def test_render_checkpoint_saved(capsys) -> None:
    render_checkpoint_saved(
        {
            "mode": "light",
            "status": "interrupted",
            "path": ".Agent01/checkpoints",
            "checkpoint_file": "checkpoint.json",
            "recovery_file": "RECOVERY.md",
            "git_commit": "abc123",
            "resume_command": "uv run Agent01 --resume ws",
        }
    )

    output = capsys.readouterr().out
    assert "Checkpoint Saved" in output
    assert "uv run Agent01 --resume ws" in output


def test_render_checkpoint_resumed(capsys) -> None:
    render_checkpoint_resumed(
        {
            "mode": "strict",
            "workspace": "ws",
            "source": "state.json",
            "fallback": False,
        }
    )

    output = capsys.readouterr().out
    assert "Checkpoint Resumed" in output
    assert "strict" in output


def test_print_custom_event_handles_checkpoint_saved(capsys) -> None:
    from Agent01.cli.formatter import print_custom_event

    print_custom_event(
        {
            "type": "checkpoint_saved",
            "mode": "light",
            "status": "finished",
            "path": ".Agent01/checkpoints",
            "resume_command": "uv run Agent01 --resume ws",
        }
    )

    output = capsys.readouterr().out
    assert "Checkpoint Saved" in output
