"""Deterministic tests for the provider-agnostic parts of agents/llm.py -- no network.
The ollama/openrouter HTTP calls are mocked here (no live Ollama server in this env) to
verify the request/response shape without depending on live infra."""
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


class _Dummy(BaseModel):
    x: int


def test_schema_tool_has_input_schema_and_no_title():
    tool = llm._schema_tool(_Dummy)
    assert tool["name"] == "submit_answer"
    assert "title" not in tool["input_schema"]
    assert tool["input_schema"]["properties"]["x"]["type"] == "integer"


def test_parse_json_strips_markdown_fence():
    # Real bug hit live: deepseek via OpenRouter wraps JSON in ```json fences even with
    # response_format=json_object set -- json.loads on the raw text blew up at char 0.
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


def test_openrouter_provider_parses_fenced_response_without_crashing(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    fake = _FakeResponse(
        {"choices": [{"message": {"content": '```json\n{"x": 3}\n```'}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    )
    monkeypatch.setattr(llm.requests, "post", lambda *a, **kw: fake)
    result = llm.complete("sys", "user", schema=_Dummy)
    assert result == _Dummy(x=3)


def test_ollama_provider_warns_and_ignores_web_search(monkeypatch, capsys):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "ollama")
    fake = _FakeResponse({"message": {"content": "plain text answer"}, "prompt_eval_count": 1, "eval_count": 1})
    monkeypatch.setattr(llm.requests, "post", lambda *a, **kw: fake)
    result = llm.complete("sys", "user", enable_web_search=True)
    assert result == "plain text answer"
    assert "web search not supported" in capsys.readouterr().out
