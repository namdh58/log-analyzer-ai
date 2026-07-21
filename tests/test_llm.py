"""Deterministic tests for the provider-agnostic parts of agents/llm.py -- no network.
The ollama HTTP calls and the deepseek openai-client calls are mocked here (no live Ollama
server, and mocking keeps the deepseek function-calling loop testable without spending real
tokens) to verify the request/response shape without depending on live infra."""
import pytest
from pydantic import BaseModel

from agents import llm


class _FakeResponse:
    def __init__(self, json_data):
        self._json = json_data

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class _FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = type("F", (), {"name": name, "arguments": arguments})()


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_unset=True):
        return {"role": "assistant", "content": self.content, "tool_calls": self.tool_calls}


class _FakeCompletion:
    def __init__(self, message, prompt_tokens=1, completion_tokens=1):
        self.choices = [type("C", (), {"message": message})()]
        self.usage = type("U", (), {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens})()


class _FakeChatCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeOpenAIClient:
    def __init__(self, responses):
        self.chat = type("Chat", (), {"completions": _FakeChatCompletions(responses)})()


class _FakeAnthropicToolBlock:
    def __init__(self, name, tool_input):
        self.type = "tool_use"
        self.name = name
        self.input = tool_input


class _FakeAnthropicResponse:
    def __init__(self, content, stop_reason="tool_use"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()


class _FakeAnthropicMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = _FakeAnthropicMessages(responses)


class _Dummy(BaseModel):
    x: int


def test_schema_tool_has_input_schema_and_no_title():
    tool = llm._schema_tool(_Dummy)
    assert tool["name"] == "submit_answer"
    assert "title" not in tool["input_schema"]
    assert tool["input_schema"]["properties"]["x"]["type"] == "integer"


def test_parse_json_strips_markdown_fence():
    # Real bug hit live (originally via deepseek/OpenRouter, same model family as the
    # current deepseek provider): fenced JSON even with response_format=json_object set --
    # json.loads on the raw text blew up at char 0. Used by the ollama branch.
    fenced = '```json\n{"x": 1}\n```'
    assert llm._parse_json(fenced) == {"x": 1}
    assert llm._parse_json('{"x": 1}') == {"x": 1}


def test_complete_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "bogus")
    with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
        llm.complete("sys", "user")


def test_ollama_provider_parses_fenced_response_without_crashing(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "ollama")
    fake = _FakeResponse(
        {"message": {"content": '```json\n{"x": 7}\n```'}, "prompt_eval_count": 10, "eval_count": 5}
    )
    monkeypatch.setattr(llm.requests, "post", lambda *a, **kw: fake)
    result = llm.complete("sys", "user", schema=_Dummy)
    assert result == _Dummy(x=7)


def test_deepseek_provider_calls_submit_answer_tool(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "DEEPSEEK_API_KEY", "test-key")
    fake_client = _FakeOpenAIClient(
        [_FakeCompletion(_FakeMessage(tool_calls=[_FakeToolCall("c1", "submit_answer", '{"x": 3}')]))]
    )
    monkeypatch.setattr("openai.OpenAI", lambda **kw: fake_client)
    result = llm.complete("sys", "user", schema=_Dummy)
    assert result == _Dummy(x=3)


def test_deepseek_provider_runs_search_tool_loop_then_submits(monkeypatch):
    # Model asks to search first, gets results fed back, then calls submit_answer --
    # exactly the classic tool-calling loop the search abstraction is meant to enable.
    monkeypatch.setattr(llm, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(llm, "SEARCH_PROVIDER", "tavily")
    search_calls = []
    monkeypatch.setattr(llm, "search_web", lambda query, max_results=3: (search_calls.append(query), [
        {"title": "Kafka best practices", "url": "https://example.com/kafka", "content": "tune batch size"}
    ])[1])

    fake_client = _FakeOpenAIClient(
        [
            _FakeCompletion(_FakeMessage(tool_calls=[_FakeToolCall("c1", "search_web", '{"query": "kafka message flood fix"}')])),
            _FakeCompletion(_FakeMessage(tool_calls=[_FakeToolCall("c2", "submit_answer", '{"x": 9}')])),
        ]
    )
    monkeypatch.setattr("openai.OpenAI", lambda **kw: fake_client)
    result = llm.complete("sys", "user", schema=_Dummy, enable_web_search=True)
    assert result == _Dummy(x=9)
    assert search_calls == ["kafka message flood fix"]
    # the tool tool_choice must be "auto" (not forced) once search is in play, so the
    # model is free to call search_web before submit_answer
    assert fake_client.chat.completions.calls[0]["tool_choice"] == "auto"


def test_anthropic_native_search_not_attached_unless_search_provider_is_anthropic(monkeypatch):
    # Regression guard: native web_search must stay OFF for anthropic unless
    # SEARCH_PROVIDER=="anthropic", even though analyst.py still always passes
    # enable_web_search=True -- the gating now happens inside llm.py.
    monkeypatch.setattr(llm, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "SEARCH_PROVIDER", "tavily")
    fake_client = _FakeAnthropicClient(
        [_FakeAnthropicResponse([_FakeAnthropicToolBlock("submit_answer", {"x": 5})])]
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda: fake_client)
    result = llm.complete("sys", "user", model_tier="smart", schema=_Dummy, enable_web_search=True)
    assert result == _Dummy(x=5)
    tool_names = [t["name"] for t in fake_client.messages.calls[0]["tools"]]
    assert "web_search" not in tool_names
    assert fake_client.messages.calls[0]["tool_choice"] == {"type": "tool", "name": "submit_answer"}


def test_anthropic_native_search_attached_when_search_provider_is_anthropic(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "SEARCH_PROVIDER", "anthropic")
    fake_client = _FakeAnthropicClient(
        [_FakeAnthropicResponse([_FakeAnthropicToolBlock("submit_answer", {"x": 8})])]
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda: fake_client)
    result = llm.complete("sys", "user", model_tier="smart", schema=_Dummy, enable_web_search=True)
    assert result == _Dummy(x=8)
    tool_names = [t["name"] for t in fake_client.messages.calls[0]["tools"]]
    assert "web_search" in tool_names
    assert fake_client.messages.calls[0]["tool_choice"] == {"type": "auto"}


def test_ollama_provider_warns_and_ignores_web_search(monkeypatch, capsys):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "ollama")
    fake = _FakeResponse({"message": {"content": "plain text answer"}, "prompt_eval_count": 1, "eval_count": 1})
    monkeypatch.setattr(llm.requests, "post", lambda *a, **kw: fake)
    result = llm.complete("sys", "user", enable_web_search=True)
    assert result == "plain text answer"
    assert "web search not supported" in capsys.readouterr().out
