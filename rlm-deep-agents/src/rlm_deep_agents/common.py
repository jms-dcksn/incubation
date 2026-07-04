"""Shared helpers for the RLM / dynamic-subagent examples.

Every example builds a Deep Agent the same way:

    agent = build_agent(subagents=[...])          # code interpreter is wired in
    run_workflow(agent, "Run a workflow that ...") # invoke + pretty-print

`build_agent` attaches `CodeInterpreterMiddleware`, which is the piece that turns
subagents into *dynamic* subagents: it gives the model an ``eval`` tool and a
built-in ``task()`` global so the model can dispatch subagents from JavaScript
instead of one tool call at a time.
"""

from __future__ import annotations

import os
import textwrap
from typing import Any, Sequence

from dotenv import load_dotenv

# Load a local .env if present so `uv run ...` picks up RLM_MODEL and API keys.
load_dotenv()

# LangChain "provider:model" identifier. The orchestrator and every subagent run
# on this model unless a subagent overrides it with its own "model" field.
DEFAULT_MODEL = os.environ.get("RLM_MODEL", "anthropic:claude-sonnet-5")

# Which env var holds the key for each provider prefix. Used only to print a
# friendly message before we try to make a real API call.
_PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
}


def get_model() -> str:
    """Return the configured orchestrator model identifier."""
    return DEFAULT_MODEL


def _required_key(model: str) -> str | None:
    provider = model.split(":", 1)[0]
    return _PROVIDER_KEYS.get(provider)


def credentials_present(model: str | None = None) -> bool:
    """True if the API key for `model`'s provider is set."""
    key = _required_key(model or get_model())
    if key is None:
        # Unknown provider: assume the user knows what they're doing.
        return True
    return bool(os.environ.get(key))


def build_agent(
    subagents: Sequence[dict[str, Any]],
    *,
    ptc: Sequence[str] | None = None,
    model: str | None = None,
    **middleware_kwargs: Any,
):
    """Create a Deep Agent whose subagents can be dispatched from interpreter code.

    Parameters
    ----------
    subagents:
        Custom subagent definitions (name / description / system_prompt / ...).
        Their *names* are what interpreter code passes as ``subagentType`` in
        ``task({...})``; their *descriptions* tell the orchestrator which role to
        reach for.
    ptc:
        Optional programmatic-tool-calling allowlist. Exposes those tools inside
        the interpreter under the ``tools`` namespace (e.g. ``tools.glob(...)``).
    model:
        Override the orchestrator model. Defaults to ``get_model()``.
    middleware_kwargs:
        Extra keyword args forwarded to ``CodeInterpreterMiddleware`` (e.g.
        ``timeout=15.0``, ``subagents=False``).
    """
    # Imported lazily so `--help`/import of this module doesn't require the
    # native QuickJS extension to be installed.
    from deepagents import create_deep_agent
    from langchain_quickjs import CodeInterpreterMiddleware

    if ptc is not None:
        middleware_kwargs["ptc"] = list(ptc)

    return create_deep_agent(
        model=model or get_model(),
        subagents=list(subagents),
        middleware=[CodeInterpreterMiddleware(**middleware_kwargs)],
    )


def _print_no_credentials(model: str) -> None:
    key = _required_key(model) or "<PROVIDER>_API_KEY"
    print(
        textwrap.dedent(
            f"""
            ─────────────────────────────────────────────────────────────
            This example builds the agent but does not call the model,
            because no API key was found for model '{model}'.

            To run it for real:
              1. cp .env.example .env
              2. set RLM_MODEL and {key} in .env   (or export them)
              3. re-run this command

            The agent object was still constructed successfully, so the
            code interpreter middleware and subagents are wired up.
            ─────────────────────────────────────────────────────────────
            """
        ).strip()
    )


def _content_to_text(content: Any) -> str:
    """Flatten LangChain message content (str or list-of-blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text") or block.get("content") or "")
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _print_message(msg: Any) -> None:
    role = getattr(msg, "type", None) or getattr(msg, "role", "?")
    name = getattr(msg, "name", None)
    label = f"{role}" + (f" ({name})" if name else "")

    text = _content_to_text(getattr(msg, "content", ""))
    tool_calls = getattr(msg, "tool_calls", None) or []

    print(f"\n=== {label} ===")
    if text.strip():
        print(text.strip())
    for call in tool_calls:
        tool_name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "?")
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
        # The interesting one for us is `eval` — that's the orchestration script.
        if tool_name == "eval":
            code = (args or {}).get("code", "")
            print("  → writes orchestration code (eval):")
            print(textwrap.indent(code, "      "))
        else:
            print(f"  → tool call: {tool_name}({args})")


def run_workflow(
    agent,
    prompt: str,
    *,
    files: dict[str, str] | None = None,
    thread_id: str = "rlm-demo",
    model: str | None = None,
) -> Any:
    """Invoke `agent` with `prompt` and pretty-print the full transcript.

    If no API key is configured for the model, we skip the call and just report
    that the agent was constructed (so the example is still useful offline).

    `files` seeds the Deep Agents virtual filesystem (path -> contents), which is
    handy for fan-out examples that discover/read files from interpreter code.
    """
    model = model or get_model()
    if not credentials_present(model):
        _print_no_credentials(model)
        return None

    payload: dict[str, Any] = {"messages": [{"role": "user", "content": prompt}]}
    if files:
        payload["files"] = files

    config = {"configurable": {"thread_id": thread_id}}

    print(f"\n>>> USER PROMPT\n{textwrap.indent(prompt.strip(), '    ')}")
    result = agent.invoke(payload, config=config)

    for msg in result.get("messages", []):
        _print_message(msg)
    return result


def print_header(title: str, description: str) -> None:
    bar = "═" * min(len(title) + 4, 70)
    print(f"\n{bar}\n  {title}\n{bar}")
    print(textwrap.fill(textwrap.dedent(description).strip(), width=70))
