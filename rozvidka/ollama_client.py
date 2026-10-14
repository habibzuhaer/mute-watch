"""Sync Ollama client — delegates to shared agents.inference."""

from __future__ import annotations

from typing import Any

from agents.inference import InferenceError as OllamaError
from agents.inference import ask, ping, strip_think as _strip_think

__all__ = ["OllamaError", "chat", "ping", "_strip_think"]


def chat(messages: list[dict[str, str]], *, model: str | None = None, temperature: float = 0.3) -> str:
    return ask(messages, model=model, temperature=temperature, num_ctx=8192, num_predict=900, src="rozvidka")
