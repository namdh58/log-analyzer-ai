"""Deterministic tests for the provider-agnostic parts of agents/llm.py -- no network."""
import pytest
from pydantic import BaseModel

from agents import llm


class _Dummy(BaseModel):
    x: int


def test_schema_tool_has_input_schema_and_no_title():
    tool = llm._schema_tool(_Dummy)
    assert tool["name"] == "submit_answer"
    assert "title" not in tool["input_schema"]
    assert tool["input_schema"]["properties"]["x"]["type"] == "integer"


def test_complete_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "bogus")
    with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
        llm.complete("sys", "user")
