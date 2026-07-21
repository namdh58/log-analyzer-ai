"""Pluggable LLM completion layer. LLM_PROVIDER: anthropic | deepseek | ollama.

Search is a SEPARATE, independent axis (SEARCH_PROVIDER: none | tavily | anthropic, see
agents/search.py) -- decoupled from any single provider's native search tool so any
LLM_PROVIDER can search. `anthropic` is the only provider with a native server-side search
tool; it's used only when SEARCH_PROVIDER=="anthropic". Everything else that wants search
(currently: deepseek) calls agents.search.search_web via classic client-side tool-calling.

Same `complete()` contract regardless of provider, so callers (agents/analyst.py) don't
know or care which provider/search backend is active.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import requests
from pydantic import BaseModel, ValidationError

from agents.search import SEARCH_PROVIDER, search_web

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")

ANTHROPIC_FAST_MODEL = "claude-haiku-4-5"
ANTHROPIC_SMART_MODEL = "claude-sonnet-4-6"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
# Native DeepSeek API by default; overridable so a key from an OpenAI-compatible reseller
# (e.g. OpenRouter, model "deepseek/deepseek-chat") can be used instead without touching code.
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")

_ANTHROPIC_NATIVE_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
_DEEPSEEK_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web for current information or external best practices.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
}


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


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)


def _parse_json(text: str) -> dict:
    # deepseek/ollama models routinely wrap JSON in markdown fences even in JSON mode --
    # strip it rather than trusting the mode flag to be honored.
    match = _JSON_FENCE_RE.match(text.strip())
    return json.loads(match.group(1) if match else text)


def _json_schema(schema: type[BaseModel]) -> dict:
    s = schema.model_json_schema()
    s.pop("title", None)
    return s


def _schema_tool(schema: type[BaseModel]) -> dict:
    """Anthropic-shaped tool definition."""
    return {
        "name": "submit_answer",
        "description": f"Submit the final {schema.__name__}.",
        "input_schema": _json_schema(schema),
    }


def _openai_function_tool(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


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
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            return _dispatch(system, user, model_tier, schema, enable_web_search)
        except (ValidationError, json.JSONDecodeError) as e:
            last_err = e
            user = f"{user}\n\n(Previous attempt returned invalid JSON: {e}. Return ONLY valid JSON matching the schema.)"
    raise last_err  # type: ignore[misc]


def _dispatch(system, user, model_tier, schema, enable_web_search):
    if LLM_PROVIDER == "anthropic":
        return _complete_anthropic(system, user, model_tier, schema, enable_web_search)
    if LLM_PROVIDER == "deepseek":
        return _complete_deepseek(system, user, schema, enable_web_search)
    if LLM_PROVIDER == "ollama":
        if enable_web_search:
            print("warning: web search not supported in ollama mode, ignoring")
        return _complete_ollama(system, user, schema)
    raise ValueError(f"unknown LLM_PROVIDER: {LLM_PROVIDER}")


def _complete_anthropic(system, user, model_tier, schema, enable_web_search):
    import anthropic

    client = anthropic.Anthropic()
    model = ANTHROPIC_SMART_MODEL if model_tier == "smart" else ANTHROPIC_FAST_MODEL
    use_native_search = enable_web_search and SEARCH_PROVIDER == "anthropic"

    if schema is None:
        resp = client.messages.create(
            model=model, max_tokens=2048, system=system, messages=[{"role": "user", "content": user}]
        )
        usage.add(resp.usage.input_tokens, resp.usage.output_tokens)
        return "".join(b.text for b in resp.content if b.type == "text")

    tool = _schema_tool(schema)
    tools = [tool]
    tool_choice = {"type": "tool", "name": "submit_answer"}
    if use_native_search:
        tools = [_ANTHROPIC_NATIVE_SEARCH_TOOL, tool]
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

        if use_native_search and resp.stop_reason == "end_turn":
            # Claude searched (or decided not to) and answered in plain text instead of
            # calling submit_answer -- force it once, now that any search is done.
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": "Now call submit_answer with your final structured answer."})
            tool_choice = {"type": "tool", "name": "submit_answer"}
            continue
        break
    raise RuntimeError(f"anthropic: model never called submit_answer (last stop_reason={resp.stop_reason})")


def _complete_deepseek(system, user, schema, enable_web_search):
    from openai import OpenAI

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set (LLM_PROVIDER=deepseek)")
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    use_search = enable_web_search and SEARCH_PROVIDER != "anthropic"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    if schema is None and not use_search:
        resp = client.chat.completions.create(model=DEEPSEEK_MODEL, messages=messages)
        usage.add(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        return resp.choices[0].message.content

    tools = []
    if schema:
        tools.append(_openai_function_tool("submit_answer", f"Submit the final {schema.__name__}.", _json_schema(schema)))
    if use_search:
        tools.append(_DEEPSEEK_SEARCH_TOOL)

    kwargs: dict = {"model": DEEPSEEK_MODEL, "messages": messages, "tools": tools}
    kwargs["tool_choice"] = "auto" if use_search else {"type": "function", "function": {"name": "submit_answer"}}

    for _ in range(6):
        resp = client.chat.completions.create(**kwargs)
        usage.add(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        message = resp.choices[0].message

        if message.tool_calls:
            messages.append(message.model_dump(exclude_unset=True))
            submit_call = next((tc for tc in message.tool_calls if tc.function.name == "submit_answer"), None)
            if submit_call:
                return schema.model_validate(json.loads(submit_call.function.arguments))
            for tc in message.tool_calls:
                if tc.function.name == "search_web":
                    args = json.loads(tc.function.arguments)
                    results = search_web(args.get("query", ""), args.get("max_results", 3))
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(results)})
            kwargs["messages"] = messages
            continue

        if schema:
            # Model answered in plain text instead of calling submit_answer -- force it,
            # now that any search round-trips are done.
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": "Now call submit_answer with your final structured answer."})
            kwargs["messages"] = messages
            kwargs["tool_choice"] = {"type": "function", "function": {"name": "submit_answer"}}
            continue
        return message.content
    raise RuntimeError("deepseek: model never called submit_answer")


def _complete_ollama(system, user, schema):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
    }
    if schema:
        payload["format"] = "json"
        payload["messages"][-1]["content"] += (
            f"\n\nRespond with ONLY a JSON object matching this schema:\n{json.dumps(_json_schema(schema))}"
        )
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    text = data["message"]["content"]
    usage.add(data.get("prompt_eval_count", 0), data.get("eval_count", 0))
    if schema:
        return schema.model_validate(_parse_json(text))
    return text
