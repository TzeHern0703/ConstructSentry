"""llm.py — single provider-agnostic LLM entry point for ConstructSentry.

PROJECT_SPEC Section 3 requires one function, ``call_llm(messages, tools)``, so
the agent code never hardcodes a provider and we can swap Anthropic <-> Gemini.

Provider selection (first one with a key wins):
  * ANTHROPIC_API_KEY -> Claude (tool use)
  * GEMINI_API_KEY / GOOGLE_API_KEY -> Gemini (function calling)
  * otherwise -> "offline": call_llm returns an empty response and callers fall
    back to deterministic reasoning. The detection logic in tools.py is real and
    works with no key, so the demo always runs.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import _env  # noqa: F401  (loads .env into os.environ on import)

# A cheap, fast model for routine ReAct steps (PROJECT_SPEC Section 8).
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"

# Grafilab Neo Cloud — OpenAI-compatible inference (hackathon sponsor credit).
GRAFILAB_BASE_URL = os.environ.get(
    "GRAFILAB_BASE_URL", "https://console-api.grafilab.ai/api/oai/v1"
)
DEFAULT_GRAFILAB_MODEL = os.environ.get("GRAFILAB_MODEL", "grafilab/qwen3.6-flash")


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = "offline"
    stop_reason: str | None = None

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


def _provider() -> str:
    if os.environ.get("GRAFILAB_API_KEY", "").strip():
        return "grafilab"
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get(
        "GOOGLE_API_KEY", ""
    ).strip():
        return "gemini"
    return "offline"


def llm_available() -> bool:
    return _provider() != "offline"


def provider_label() -> str:
    """Human-readable label for the UI (honesty about what's driving reasoning)."""
    p = _provider()
    return {
        "grafilab": f"Grafilab ({DEFAULT_GRAFILAB_MODEL})",
        "anthropic": f"Claude ({DEFAULT_ANTHROPIC_MODEL})",
        "gemini": f"Gemini ({DEFAULT_GEMINI_MODEL})",
        "offline": "offline (deterministic reasoning)",
    }[p]


# --- Grafilab (OpenAI-compatible) ------------------------------------------

def _call_grafilab(messages, tools, system, model, max_tokens) -> LLMResponse:
    import requests

    chat = []
    if system:
        chat.append({"role": "system", "content": system})
    for m in messages:
        content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        chat.append({"role": m["role"], "content": content})

    resp = requests.post(
        f"{GRAFILAB_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {os.environ.get('GRAFILAB_API_KEY','')}",
            "Content-Type": "application/json",
        },
        json={
            "model": model or DEFAULT_GRAFILAB_MODEL,
            "messages": chat,
            "max_tokens": max_tokens,
            "temperature": 0.5,
            # qwen3.6 is a reasoning model — disable "thinking" so it answers
            # directly: fast (~3s) and no wasted reasoning tokens (saves credit).
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=45,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return LLMResponse(text=text or "", provider="grafilab")


# --- Anthropic -------------------------------------------------------------

def _call_anthropic(messages, tools, system, model, max_tokens) -> LLMResponse:
    import anthropic

    client = anthropic.Anthropic()
    kwargs = {
        "model": model or DEFAULT_ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    resp = client.messages.create(**kwargs)

    text_parts, tool_calls = [], []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

    return LLMResponse(
        text="".join(text_parts),
        tool_calls=tool_calls,
        provider="anthropic",
        stop_reason=resp.stop_reason,
    )


# --- Gemini ----------------------------------------------------------------

def _call_gemini(messages, tools, system, model, max_tokens) -> LLMResponse:
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
    import google.generativeai as genai

    genai.configure(
        api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    # Flatten our message list into Gemini's "contents" format.
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        text = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        contents.append({"role": role, "parts": [text]})

    gmodel = genai.GenerativeModel(
        model or DEFAULT_GEMINI_MODEL, system_instruction=system
    )
    resp = gmodel.generate_content(
        contents, generation_config={"max_output_tokens": max_tokens}
    )
    return LLMResponse(text=resp.text or "", provider="gemini")


# --- Public entry point ----------------------------------------------------

def call_llm(messages, tools=None, system=None, model=None, max_tokens=1024) -> LLMResponse:
    """Provider-agnostic chat completion.

    Args:
        messages: list of {"role": "user"|"assistant", "content": str|blocks}.
        tools: optional tool schemas (Anthropic tool-use format).
        system: optional system prompt string.
        model: optional model override.
        max_tokens: response cap.

    Returns an LLMResponse. On any error or with no key, returns an empty
    offline response so callers degrade gracefully.
    """
    provider = _provider()
    try:
        if provider == "grafilab":
            return _call_grafilab(messages, tools, system, model, max_tokens)
        if provider == "anthropic":
            return _call_anthropic(messages, tools, system, model, max_tokens)
        if provider == "gemini":
            return _call_gemini(messages, tools, system, model, max_tokens)
    except Exception as exc:  # network/SDK/parse errors -> offline fallback
        return LLMResponse(text="", provider="offline", stop_reason=f"error:{exc}")
    return LLMResponse(text="", provider="offline")


def complete(prompt: str, system: str | None = None, max_tokens: int = 700) -> str | None:
    """Convenience single-turn text completion. Returns None when offline."""
    resp = call_llm([{"role": "user", "content": prompt}], system=system, max_tokens=max_tokens)
    return resp.text or None


if __name__ == "__main__":
    print("provider:", provider_label())
    print("available:", llm_available())
    out = complete("Say 'ConstructSentry online' in three words.")
    print("completion:", out)
