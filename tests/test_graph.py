from langchain_core.messages import AIMessage
from Agent01.graph.nodes import intent_router_node, intent_route_fn, chat_responder_node


def test_intent_router_routes_chat_with_model_json(monkeypatch) -> None:
    class FakeModel:
        def invoke(self, messages):
            return AIMessage(content='{"route":"chat","reason":"greeting","confidence":0.92}')

    monkeypatch.setattr("Agent01.graph.nodes.create_model", lambda: FakeModel())

    result = intent_router_node({"task": "你好"})

    assert result["intent_route"] == "chat"
    assert result["intent_reason"] == "greeting"
    assert result["intent_confidence"] == 0.92
    assert intent_route_fn(result) == "chat_responder"


def test_intent_router_routes_workflow_with_model_json(monkeypatch) -> None:
    class FakeModel:
        def invoke(self, messages):
            return AIMessage(content='{"route":"workflow","reason":"needs files","confidence":0.88}')

    monkeypatch.setattr("Agent01.graph.nodes.create_model", lambda: FakeModel())

    result = intent_router_node({"task": "帮我创建一个 HTML 页面"})

    assert result["intent_route"] == "workflow"
    assert intent_route_fn(result) == "planner"


def test_intent_router_invalid_json_defaults_to_workflow(monkeypatch) -> None:
    class FakeModel:
        def invoke(self, messages):
            return AIMessage(content="not json")

    monkeypatch.setattr("Agent01.graph.nodes.create_model", lambda: FakeModel())

    result = intent_router_node({"task": "你好"})

    assert result["intent_route"] == "workflow"
    assert intent_route_fn(result) == "planner"


def test_chat_responder_node_returns_chat_response(monkeypatch) -> None:
    class FakeModel:
        def invoke(self, messages):
            return AIMessage(content="你好，我在。")

    monkeypatch.setattr("Agent01.graph.nodes.create_model", lambda: FakeModel())

    result = chat_responder_node({"task": "你好", "intent_reason": "greeting"})

    assert result["chat_response"] == "你好，我在。"
    assert result["final_answer"] == "你好，我在。"
