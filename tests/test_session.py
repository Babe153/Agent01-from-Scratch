from __future__ import annotations

import json

from Agent01.core.session import (
    SESSION_SUMMARY_FILE,
    append_assistant_turn,
    append_user_turn,
    build_session_context,
    load_or_create_session,
    save_session,
    session_file,
)


def test_session_create_save_and_context(tmp_path) -> None:
    session = load_or_create_session(tmp_path)
    turn = append_user_turn(session, "帮我创建一个 app.py")
    append_assistant_turn(session, turn=turn, route="workflow", content="created app.py")
    save_session(tmp_path, session)

    assert session_file(tmp_path).exists()
    assert (tmp_path / SESSION_SUMMARY_FILE).exists()

    saved = json.loads(session_file(tmp_path).read_text(encoding="utf-8"))
    assert saved["turn_index"] == 1
    assert saved["last_route"] == "workflow"

    context = build_session_context(tmp_path, saved)
    assert "帮我创建一个 app.py" in context
    assert "created app.py" in context


def test_session_history_is_compacted(tmp_path) -> None:
    session = load_or_create_session(tmp_path)

    for idx in range(25):
        turn = append_user_turn(session, f"user turn {idx}")
        append_assistant_turn(session, turn=turn, route="chat", content=f"assistant turn {idx}")

    save_session(tmp_path, session)
    saved = json.loads(session_file(tmp_path).read_text(encoding="utf-8"))

    assert len(saved["recent_turns"]) <= 18
    assert "user turn 0" in saved["summary"]


def test_session_context_lists_workspace_files(tmp_path) -> None:
    (tmp_path / "app.py").write_text("print('hello')", encoding="utf-8")
    session = load_or_create_session(tmp_path)
    context = json.loads(build_session_context(tmp_path, session))
    assert "app.py" in context["recent_files"]
    assert not any(path.startswith(".Agent01/session/") for path in context["recent_files"])


def test_second_turn_receives_persisted_first_turn(monkeypatch, tmp_path) -> None:
    from Agent01.core.agent import stream_session_events

    contexts = []

    class Entry:
        def stream(self, inputs, stream_mode):
            contexts.append(inputs["session_context"])
            yield "custom", {"type": "intent_decision", "route": "chat"}
            yield "updates", {"chat_responder": {"chat_response": "记住了，使用蓝色主题。"}}

    monkeypatch.setattr("Agent01.core.agent.build_entry_workflow", lambda: Entry())
    list(stream_session_events("我喜欢蓝色主题", session_workspace=tmp_path))
    first = load_or_create_session(tmp_path)
    list(stream_session_events("我喜欢什么主题？", session_workspace=tmp_path))
    second = load_or_create_session(tmp_path)
    assert first["session_id"] == second["session_id"]
    assert second["turn_index"] == 2
    assert "我喜欢蓝色主题" in contexts[1]
    assert "记住了，使用蓝色主题。" in contexts[1]
