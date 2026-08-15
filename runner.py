"""Streaming inference across local providers.

Each ``run_*`` function is a generator yielding tokens as they arrive. The
top-level ``run_model`` dispatches based on the provider name.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Callable, Generator, Iterable

logger = logging.getLogger(__name__)

USER_AGENT = "Nameweaver/0.2"

OLLAMA_GENERATE = "http://localhost:11434/api/generate"
OLLAMA_CHAT = "http://localhost:11434/api/chat"
LM_STUDIO_CHAT = "http://localhost:1234/v1/chat/completions"
DMR_CHAT = "http://localhost:12434/engines/v1/chat/completions"

CancelFn = Callable[[], bool]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _post_stream(
    url: str,
    payload: dict,
    headers: dict | None = None,
    timeout: float = 300.0,
    should_cancel: CancelFn | None = None,
) -> Generator[bytes, None, None]:
    """POST a JSON body and iterate over response lines.

    Always closes the underlying socket — whether we finish, the caller
    aborts the generator (GeneratorExit), or cancellation fires mid-stream.
    """
    body = json.dumps(payload).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, method="POST", headers=req_headers)
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        for line in resp:
            if should_cancel and should_cancel():
                return
            if line:
                yield line
    finally:
        resp.close()


def _parse_sse_data(raw: bytes) -> dict | None:
    """Parse an SSE 'data: {...}' line, return the JSON dict or None."""
    line = raw.decode("utf-8", errors="replace").strip()
    if not line or not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return {"_done": True}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Provider-specific streamers
# ---------------------------------------------------------------------------


def run_ollama(
    model: str,
    prompt: str,
    *,
    system: str = "",
    should_cancel: CancelFn | None = None,
) -> Generator[str, None, None]:
    """Stream tokens from Ollama's /api/generate endpoint."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
    }
    if system:
        payload["system"] = system

    try:
        for raw in _post_stream(OLLAMA_GENERATE, payload, should_cancel=should_cancel):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            token = event.get("response", "")
            if token:
                yield token
            if event.get("done"):
                return
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("Ollama inference failed: %s", exc)
        yield f"\n[error: {exc}]"


def _run_openai_compatible(
    url: str,
    model: str,
    messages: list[dict],
    should_cancel: CancelFn | None = None,
) -> Generator[str, None, None]:
    """Stream tokens from an OpenAI-compatible /v1/chat/completions endpoint."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    try:
        for raw in _post_stream(url, payload, should_cancel=should_cancel):
            event = _parse_sse_data(raw)
            if event is None:
                continue
            if event.get("_done"):
                return
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            token = delta.get("content") or ""
            if token:
                yield token
            if choices[0].get("finish_reason"):
                return
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("OpenAI-compat inference failed (%s): %s", url, exc)
        yield f"\n[error: {exc}]"


def run_lm_studio(
    model: str,
    prompt: str,
    *,
    system: str = "",
    should_cancel: CancelFn | None = None,
) -> Generator[str, None, None]:
    messages = _build_messages(prompt, system)
    yield from _run_openai_compatible(LM_STUDIO_CHAT, model, messages, should_cancel)


def run_docker_model_runner(
    model: str,
    prompt: str,
    *,
    system: str = "",
    should_cancel: CancelFn | None = None,
) -> Generator[str, None, None]:
    messages = _build_messages(prompt, system)
    yield from _run_openai_compatible(DMR_CHAT, model, messages, should_cancel)


def _build_messages(prompt: str, system: str = "") -> list[dict]:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def run_model(
    model_name: str,
    provider: str,
    prompt: str,
    *,
    system: str = "",
    should_cancel: CancelFn | None = None,
) -> Generator[str, None, None]:
    """Route inference to the appropriate provider."""
    p = (provider or "").strip().lower()
    if p == "ollama":
        yield from run_ollama(model_name, prompt, system=system, should_cancel=should_cancel)
    elif p in ("lm studio", "lmstudio"):
        yield from run_lm_studio(model_name, prompt, system=system, should_cancel=should_cancel)
    elif p in ("docker", "docker model runner", "dmr"):
        yield from run_docker_model_runner(model_name, prompt, system=system, should_cancel=should_cancel)
    else:
        yield f"[error: provider '{provider}' not supported for streaming inference]"


def available_providers_for_model(
    model_name: str,
    provider_statuses: Iterable,
) -> list[str]:
    """Return providers where this model appears installed."""
    from models import name_matches_installed

    result = []
    for p in provider_statuses:
        if not getattr(p, "available", False):
            continue
        installed = getattr(p, "installed_models", set()) or set()
        if name_matches_installed(model_name, installed):
            result.append(p.name)
    return result
