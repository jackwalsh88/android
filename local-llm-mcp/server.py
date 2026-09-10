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
import os

import httpx
from mcp.server.fastmcp import FastMCP

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
