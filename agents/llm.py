"""Pluggable LLM completion layer. LLM_PROVIDER: anthropic | openrouter | ollama.

`openrouter` is a demo-session addition (not in the original CLAUDE.md tech stack): lets
this project run against deepseek/deepseek-chat via https://openrouter.ai when no
ANTHROPIC_API_KEY is available yet. Same `complete()` contract as anthropic/ollama, so
callers (agents/analyst.py) don't know which provider is active.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

import requests
from pydantic import BaseModel, ValidationError

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")

ANTHROPIC_FAST_MODEL = "claude-haiku-4-5"
ANTHROPIC_SMART_MODEL = "claude-sonnet-4-6"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat")

_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


@dataclass
class _Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def __str__(self) -> str:
        return f"LLM calls: {self.calls} | in: {self.input_tokens} tok | out: {self.output_tokens} tok"


usage = _Usage()  # module-level counter; the demo runner prints str(usage) after a run


def _schema_tool(schema: type[BaseModel]) -> dict:
    input_schema = schema.model_json_schema()
    input_schema.pop("title", None)
    return {
        "name": "submit_answer",
        "description": f"Submit the final {schema.__name__}.",
        "input_schema": input_schema,
    }


def complete(
    system: str,
    user: str,
    model_tier: str = "fast",
    schema: Optional[type[BaseModel]] = None,
    enable_web_search: bool = False,
) -> str | BaseModel:
    """Fast/smart tier text or (if `schema`) a validated instance of it. 1 retry on
    schema-validation failure, shared across providers."""
    attempts = 2 if schema else 1
    last_err: ValidationError | None = None
    for _ in range(attempts):
        try:
            return _dispatch(system, user, model_tier, schema, enable_web_search)
        except ValidationError as e:
            last_err = e
            user = f"{user}\n\n(Previous attempt returned invalid JSON: {e}. Return ONLY valid JSON matching the schema.)"
    raise last_err  # type: ignore[misc]


def _dispatch(system, user, model_tier, schema, enable_web_search):
    if LLM_PROVIDER == "anthropic":
        return _complete_anthropic(system, user, model_tier, schema, enable_web_search)
    if LLM_PROVIDER == "openrouter":
        if enable_web_search:
            print("warning: web search not supported on openrouter provider, ignoring")
        return _complete_openrouter(system, user, schema)
    if LLM_PROVIDER == "ollama":
        if enable_web_search:
            print("warning: web search not supported in ollama mode, ignoring")
        return _complete_ollama(system, user, schema)
    raise ValueError(f"unknown LLM_PROVIDER: {LLM_PROVIDER}")


def _complete_anthropic(system, user, model_tier, schema, enable_web_search):
    import anthropic

    client = anthropic.Anthropic()
    model = ANTHROPIC_SMART_MODEL if model_tier == "smart" else ANTHROPIC_FAST_MODEL

    if schema is None:
        resp = client.messages.create(
            model=model, max_tokens=2048, system=system, messages=[{"role": "user", "content": user}]
        )
        usage.add(resp.usage.input_tokens, resp.usage.output_tokens)
        return "".join(b.text for b in resp.content if b.type == "text")

    tool = _schema_tool(schema)
    tools = [tool]
    tool_choice = {"type": "tool", "name": "submit_answer"}
    if enable_web_search:
        tools = [_WEB_SEARCH_TOOL, tool]
        tool_choice = {"type": "auto"}

    messages = [{"role": "user", "content": user}]
    for _ in range(4):
        resp = client.messages.create(
            model=model, max_tokens=4096, system=system, messages=messages, tools=tools, tool_choice=tool_choice
        )
        usage.add(resp.usage.input_tokens, resp.usage.output_tokens)

        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue

        tool_call = next((b for b in resp.content if b.type == "tool_use" and b.name == "submit_answer"), None)
        if tool_call:
            return schema.model_validate(tool_call.input)

        if enable_web_search and resp.stop_reason == "end_turn":
            # Claude searched (or decided not to) and answered in plain text instead of
            # calling submit_answer -- force it once, now that any search is done.
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": "Now call submit_answer with your final structured answer."})
            tool_choice = {"type": "tool", "name": "submit_answer"}
            continue
        break
    raise RuntimeError(f"anthropic: model never called submit_answer (last stop_reason={resp.stop_reason})")


def _complete_openrouter(system, user, schema):
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set (LLM_PROVIDER=openrouter)")
    user_content = user
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
    }
    if schema:
        payload["messages"][-1]["content"] += (
            f"\n\nRespond with ONLY a JSON object matching this schema, no prose, no markdown fences:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        payload["response_format"] = {"type": "json_object"}
    resp = requests.post(
        OPENROUTER_URL, headers={"Authorization": f"Bearer {api_key}"}, json=payload, timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    u = data.get("usage", {})
    usage.add(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
    if schema:
        return schema.model_validate(json.loads(text))
    return text


def _complete_ollama(system, user, schema):
    user_content = user
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        "stream": False,
    }
    if schema:
        payload["format"] = "json"
        payload["messages"][-1]["content"] += (
            f"\n\nRespond with ONLY a JSON object matching this schema:\n{json.dumps(schema.model_json_schema())}"
        )
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    text = data["message"]["content"]
    usage.add(data.get("prompt_eval_count", 0), data.get("eval_count", 0))
    if schema:
        return schema.model_validate(json.loads(text))
    return text
