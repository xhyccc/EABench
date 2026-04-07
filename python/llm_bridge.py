#!/usr/bin/env python3
"""LLM bridge – subprocess shim between the Rust generator and the official
OpenAI Python SDK.

The Rust generator spawns this script as a child process, writes a JSON
request to its stdin, and reads a JSON response from stdout.  All
authentication, retry, and error-handling logic lives here, backed by the
official ``openai`` package.

Request format (stdin, one JSON object):

    {
      "provider": "azure" | "openai",
      "config": {
        // Azure
        "api_key":         "...",
        "azure_endpoint":  "https://<resource>.cognitiveservices.azure.com/",
        "deployment_name": "gpt-4o",
        "api_version":     "2024-12-01-preview",
        // OpenAI
        "api_key":         "...",
        "base_url":        "https://...",   // optional
        "model":           "gpt-4o",
        // Common
        "temperature":     0.7,             // default 0.7
        "max_retries":     3                // default 3
      },
      "messages": [{"role": "...", "content": "...", ...}, ...],
      "tools":    [...]   // optional, may be absent or empty
    }

Success response (stdout, then exit 0):

    {
      "content":    "..." | null,
      "tool_calls": [{"id": "...", "name": "...", "arguments": {...}}, ...] | null,
      "usage":      {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N} | null
    }

Error response (stdout, then exit 1):

    {"error": "...message..."}
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
import traceback
from typing import Any


def _inject_venv_if_needed() -> None:
    """Ensure the repo's .venv site-packages are on sys.path.

    When the Rust binary shells out to a system ``python3`` that does not have
    ``openai`` installed, this function locates the venv next to the repo root
    and prepends its site-packages so the import succeeds.
    """
    try:
        import openai  # noqa: F401
        return  # already importable – nothing to do
    except ImportError:
        pass

    # __file__ is …/python/llm_bridge.py  →  repo root is one level up
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Prefer the site-packages that match the running Python version exactly
    # (e.g. python3.12), then fall back to any valid-looking venv library dir.
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates: list[str] = []

    exact = os.path.join(repo_root, ".venv", "lib", pyver, "site-packages")
    if os.path.isdir(exact):
        candidates.append(exact)

    if not candidates:
        for sp in sorted(
            glob.glob(os.path.join(repo_root, ".venv", "lib", "python*", "site-packages")),
        ):
            # Skip dirs with spaces – those are macOS Finder duplicates
            if " " not in os.path.basename(os.path.dirname(sp)) and os.path.isdir(sp):
                candidates.append(sp)

    for sp in candidates:
        if sp not in sys.path:
            sys.path.insert(0, sp)


_inject_venv_if_needed()


def main() -> int:
    try:
        raw = sys.stdin.read()
        request: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        _die(f"Failed to parse request from stdin: {exc}")

    provider = request.get("provider", "openai").lower()
    config: dict[str, Any] = request.get("config", {})
    messages: list[dict] = request.get("messages", [])
    tools: list[dict] = request.get("tools") or []

    temperature = float(config.get("temperature", 0.7))
    max_retries = int(config.get("max_retries", 3))

    try:
        if provider == "azure":
            from openai import AzureOpenAI
            client = AzureOpenAI(
                api_key=config["api_key"],
                azure_endpoint=config["azure_endpoint"],
                api_version=config["api_version"],
                max_retries=max_retries,
            )
            model = config["deployment_name"]
        else:
            from openai import OpenAI
            kwargs: dict[str, Any] = {
                "api_key": config["api_key"],
                "max_retries": max_retries,
            }
            if config.get("base_url"):
                kwargs["base_url"] = config["base_url"]
            client = OpenAI(**kwargs)
            model = config["model"]

        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            call_kwargs["tools"] = tools

        # Retry with exponential backoff on 429 RateLimitError.
        # The SDK's built-in max_retries does not reliably cover rate limits.
        from openai import RateLimitError
        _rate_limit_retries = 6
        _backoff = 5.0  # seconds, doubles each attempt
        for _attempt in range(_rate_limit_retries + 1):
            try:
                response = client.chat.completions.create(**call_kwargs)
                break
            except RateLimitError:
                if _attempt == _rate_limit_retries:
                    raise
                wait = _backoff * (2 ** _attempt)
                print(
                    f"[llm_bridge] 429 rate limit – retrying in {wait:.0f}s "
                    f"(attempt {_attempt + 1}/{_rate_limit_retries})",
                    file=sys.stderr,
                )
                time.sleep(wait)

    except Exception:
        _die(traceback.format_exc())

    choice = response.choices[0]
    msg = choice.message

    content: str | None = msg.content or None

    tool_calls = None
    if msg.tool_calls:
        out: list[dict] = []
        for tc in msg.tool_calls:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            out.append({
                "id":        tc.id,
                "name":      tc.function.name,
                "arguments": arguments,
            })
        if out:
            tool_calls = out

    usage = None
    if response.usage:
        usage = {
            "prompt_tokens":     response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens":      response.usage.total_tokens,
        }

    print(json.dumps({"content": content, "tool_calls": tool_calls, "usage": usage}))
    return 0


def _die(msg: str) -> None:
    print(json.dumps({"error": str(msg)}))
    sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
