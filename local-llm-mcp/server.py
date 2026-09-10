"""
Local LLM MCP server.

Exposes a local vLLM-served model (default: Qwen3.8-27B) as MCP tools so that
Claude Code can delegate work to it — single completions and concurrent batch
completions that exploit vLLM's continuous batching.

Backend is any OpenAI-compatible endpoint, so this also works against Ollama
(set VLLM_URL=http://localhost:11434/v1) without code changes.

Env vars:
  VLLM_URL     Base URL of the OpenAI-compatible API (default http://localhost:8000/v1)
  VLLM_MODEL   Model name as the server reports it   (default Qwen/Qwen3.8-27B)
  VLLM_API_KEY API key if the server requires one     (default "EMPTY")
  LLM_MAX_CONCURRENCY  Cap on in-flight batch requests (default 16)
"""

import asyncio
import base64
import glob as globlib
import mimetypes
import os

import httpx
from mcp.server.fastmcp import FastMCP

MAX_FILE_CHARS = int(os.environ.get("LLM_MAX_FILE_CHARS", "200000"))

VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000/v1").rstrip("/")
MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3.8-27B")
API_KEY = os.environ.get("VLLM_API_KEY", "EMPTY")
MAX_CONCURRENCY = int(os.environ.get("LLM_MAX_CONCURRENCY", "16"))

mcp = FastMCP("local-llm")
_headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
_sem = asyncio.Semaphore(MAX_CONCURRENCY)


async def _complete(
    client: httpx.AsyncClient,
    prompt: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with _sem:
        resp = await client.post(
            f"{VLLM_URL}/chat/completions", json=payload, headers=_headers
        )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


@mcp.tool()
async def generate(
    prompt: str,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """Send one prompt to the local model and return its completion.

    Use for a single delegated subtask. For many independent prompts, prefer
    generate_batch — it runs them concurrently and is far faster on vLLM.
    """
    async with httpx.AsyncClient(timeout=300) as client:
        return await _complete(client, prompt, system, temperature, max_tokens)


@mcp.tool()
async def generate_batch(
    prompts: list[str],
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> list[str]:
    """Send many prompts to the local model concurrently; return completions in order.

    Exploits vLLM's continuous batching for high throughput. Use this to fan out
    bulk work — classifying, summarizing, or transforming many items at once —
    instead of calling generate in a loop. Results align 1:1 with `prompts`.
    Concurrency is capped by LLM_MAX_CONCURRENCY (default 16).
    """
    async with httpx.AsyncClient(timeout=600) as client:
        tasks = [
            _complete(client, p, system, temperature, max_tokens) for p in prompts
        ]
        return await asyncio.gather(*tasks)


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(MAX_FILE_CHARS)


@mcp.tool()
async def summarize_files(
    paths: list[str],
    instruction: str,
    system: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> list[dict]:
    """Apply `instruction` to each file's CONTENTS on the local model, concurrently.

    The server reads each file itself, so file contents NEVER enter Claude's
    context — only the model's condensed results return. This is the correct way
    to offload bulk file processing (summaries, extraction, classification) while
    protecting Claude's context window.

    `paths` may include glob patterns (e.g. "src/**/*.py"); they are expanded
    server-side. Each file is truncated to LLM_MAX_FILE_CHARS (default 200k).
    `instruction` is the per-file task, e.g. "List SQL-injection-prone lines as
    JSON: [{line, tainted_var}]." Returns one {path, result} per file, in order;
    unreadable files return {path, error}. Low temperature by default for
    deterministic extraction.
    """
    expanded: list[str] = []
    for p in paths:
        matches = globlib.glob(p, recursive=True)
        expanded.extend(sorted(matches) if matches else [p])

    async def _one(client: httpx.AsyncClient, path: str) -> dict:
        try:
            content = _read_file(path)
        except Exception as e:  # noqa: BLE001
            return {"path": path, "error": str(e)}
        prompt = f"{instruction}\n\n--- FILE: {path} ---\n{content}"
        try:
            out = await _complete(client, prompt, system, temperature, max_tokens)
            return {"path": path, "result": out}
        except Exception as e:  # noqa: BLE001
            return {"path": path, "error": str(e)}

    async with httpx.AsyncClient(timeout=600) as client:
        return await asyncio.gather(*[_one(client, p) for p in expanded])


async def _complete_vision(
    client: httpx.AsyncClient,
    prompt: str,
    image_data_uri: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_uri}},
            ],
        }
    )
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with _sem:
        resp = await client.post(
            f"{VLLM_URL}/chat/completions", json=payload, headers=_headers
        )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _image_data_uri(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


@mcp.tool()
async def describe_images(
    paths: list[str],
    instruction: str,
    system: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> list[dict]:
    """Apply `instruction` to each IMAGE on the local model, concurrently (vision).

    Requires a vision-capable model served with multimodal support (e.g. a Qwen
    VL / natively-multimodal checkpoint). Against a text-only model this errors.

    The server reads and base64-encodes each image itself, so image bytes never
    enter Claude's context — only the model's textual results return. Use this to
    offload bulk image work: OCR, description, classification, extracting fields
    from screenshots/receipts. `paths` accepts globs. Returns one {path, result}
    per image (or {path, error}); results in order.
    """
    expanded: list[str] = []
    for p in paths:
        matches = globlib.glob(p, recursive=True)
        expanded.extend(sorted(matches) if matches else [p])

    async def _one(client: httpx.AsyncClient, path: str) -> dict:
        try:
            uri = _image_data_uri(path)
        except Exception as e:  # noqa: BLE001
            return {"path": path, "error": str(e)}
        try:
            out = await _complete_vision(
                client, instruction, uri, system, temperature, max_tokens
            )
            return {"path": path, "result": out}
        except Exception as e:  # noqa: BLE001
            return {"path": path, "error": str(e)}

    async with httpx.AsyncClient(timeout=600) as client:
        return await asyncio.gather(*[_one(client, p) for p in expanded])


@mcp.tool()
async def health() -> str:
    """Report whether the local model server is reachable and which model is loaded."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{VLLM_URL}/models", headers=_headers)
        resp.raise_for_status()
        ids = [m.get("id") for m in resp.json().get("data", [])]
        return f"OK — {VLLM_URL} reachable. Models: {', '.join(ids) or '(none)'}"
    except Exception as e:  # noqa: BLE001
        return f"UNREACHABLE — {VLLM_URL}: {e}"


if __name__ == "__main__":
    mcp.run()
