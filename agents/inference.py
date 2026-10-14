"""Shared Ollama inference — any swarm module may ask(), none must."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from agents.config import DATA_DIR, MODEL, OLLAMA_HOST, OLLAMA_TIMEOUT, TOKENS_FILE

logger = logging.getLogger(__name__)


class InferenceError(RuntimeError):
    pass


def strip_think(text: str) -> str:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<think>[\s\S]*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def ping() -> dict[str, Any]:
    try:
        data = _get("/api/tags", timeout=5.0)
        models = [m.get("name") for m in data.get("models") or []]
        return {"ok": True, "models": models, "host": OLLAMA_HOST, "model": MODEL}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "models": [], "host": OLLAMA_HOST, "model": MODEL}


def ask(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    num_ctx: int = 8192,
    num_predict: int = 900,
    timeout: float | None = None,
    src: str = "orch",
) -> str:
    payload = {
        "model": model or MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    t0 = time.monotonic()
    data = _post("/api/chat", payload, timeout=timeout if timeout is not None else OLLAMA_TIMEOUT)
    msg = data.get("message") or {}
    content = strip_think((msg.get("content") or "").strip())
    _record_tokens(
        src=src,
        model=payload["model"],
        prompt=int(data.get("prompt_eval_count") or 0),
        completion=int(data.get("eval_count") or 0),
        elapsed=time.monotonic() - t0,
    )
    return content


def load_tokens() -> dict[str, Any]:
    if not TOKENS_FILE.exists():
        return {"prompt": 0, "completion": 0, "calls": 0, "by_src": {}, "updated_at": None}
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"prompt": 0, "completion": 0, "calls": 0, "by_src": {}, "updated_at": None}


def _record_tokens(*, src: str, model: str, prompt: int, completion: int, elapsed: float) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    st = load_tokens()
    st["prompt"] = int(st.get("prompt") or 0) + prompt
    st["completion"] = int(st.get("completion") or 0) + completion
    st["calls"] = int(st.get("calls") or 0) + 1
    by_src = st.setdefault("by_src", {})
    slot = by_src.setdefault(src, {"prompt": 0, "completion": 0, "calls": 0})
    slot["prompt"] += prompt
    slot["completion"] += completion
    slot["calls"] += 1
    st["last_model"] = model
    st["last_elapsed_sec"] = round(elapsed, 2)
    st["updated_at"] = datetime.now().astimezone().isoformat()
    tmp = TOKENS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TOKENS_FILE)


def _get(path: str, *, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(OLLAMA_HOST + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise InferenceError(f"Ollama недоступна ({OLLAMA_HOST}): {exc}") from exc


def _post(path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_HOST + path,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except TimeoutError as exc:
        raise InferenceError(
            f"Ollama timeout after {timeout:.0f}s ({payload.get('model')} @ {OLLAMA_HOST})"
        ) from exc
    except urllib.error.URLError as exc:
        raise InferenceError(
            f"Ollama chat failed ({payload.get('model')} @ {OLLAMA_HOST}): {exc}"
        ) from exc
    except OSError as exc:
        raise InferenceError(
            f"Ollama OS error ({payload.get('model')} @ {OLLAMA_HOST}): {exc}"
        ) from exc
