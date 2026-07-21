"""Client-side, provider-agnostic web search -- decoupled from Anthropic's native
web_search tool so any LLM_PROVIDER can search. SEARCH_PROVIDER: none | tavily | anthropic
(the "anthropic" value is only meaningful to agents/llm.py's anthropic branch, which uses
its own native tool instead of calling this module)."""
import os

import requests

SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "none")
_TAVILY_URL = "https://api.tavily.com/search"


def search_web(query: str, max_results: int = 3) -> list[dict]:
    """Returns [{title, url, content}, ...]. Never raises -- a missing key or an unknown
    provider degrades to an empty result list rather than crashing the analyst."""
    if SEARCH_PROVIDER == "tavily":
        return _search_tavily(query, max_results)
    if SEARCH_PROVIDER == "none":
        print(f"debug: search_web called with SEARCH_PROVIDER=none, skipping search for: {query!r}")
        return []
    print(f"warning: unknown SEARCH_PROVIDER={SEARCH_PROVIDER!r}, skipping search")
    return []


def _search_tavily(query: str, max_results: int) -> list[dict]:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print("warning: SEARCH_PROVIDER=tavily but TAVILY_API_KEY not set, skipping search")
        return []
    resp = requests.post(
        _TAVILY_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"query": query, "max_results": max_results, "include_answer": True},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    if data.get("answer"):
        # Tavily's own synthesized, LLM-ready summary -- prefer it over raw per-source
        # snippets. No URL of its own, so it's excluded when the caller builds `references`.
        results.append({"title": "Tavily summary", "url": "", "content": data["answer"]})
    for r in data.get("results", []):
        results.append({"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")})
    return results[:max_results]
