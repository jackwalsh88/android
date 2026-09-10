# local-llm-mcp

An MCP server that exposes a local vLLM-served model (default Qwen3.8-27B) to
Claude Code as tools, so Claude can delegate work to it — single completions and
concurrent batch completions that use vLLM's continuous batching.

Backend is any OpenAI-compatible endpoint, so it also works against Ollama by
changing `VLLM_URL`.

## Tools

- `generate(prompt, system?, temperature?, max_tokens?)` — one completion.
- `generate_batch(prompts[], system?, temperature?, max_tokens?)` — many prompts
  fired concurrently; results align 1:1 with input. Use for fan-out/bulk work.
- `summarize_files(paths[], instruction, system?, temperature?, max_tokens?)` —
  applies `instruction` to each file's CONTENTS concurrently. The **server reads
  the files**, so their contents never enter Claude's context — only the condensed
  results return. `paths` accepts globs (e.g. `src/**/*.py`). This is the correct
  tool for offloading bulk file processing while protecting Claude's context.
- `health()` — check the server is reachable and which model is loaded.

### Files: keep contents out of Claude's context

The model only takes text. A file "works" only when its contents become text in
the prompt — and the point of the apprentice pattern is that Claude must NOT be
the one reading them (that routes the volume through Claude's context and defeats
the purpose). Use `summarize_files`, which reads paths/globs server-side, rather
than reading files with Claude and passing them to `generate`/`generate_batch`.

**Non-text files** (images, PDF, audio) are not readable by this text model.
Extract text first (OCR/parser) or route them to a multimodal model — Qwen3.8-27B
here is text-only. `summarize_files` reads files as UTF-8 and truncates each to
`LLM_MAX_FILE_CHARS` (default 200k chars).

## 1. Serve the model with vLLM (on the RTX 5090, Linux/CUDA)

A 27B in FP16 is ~54GB and will NOT fit in 32GB VRAM. Run a quantized checkpoint.

**Option A — AWQ int4 (~16GB, most headroom, best concurrency):**
```
pip install vllm
vllm serve Qwen/Qwen3.8-27B-AWQ \
  --quantization awq_marlin \
  --gpu-memory-utilization 0.90 \
  --max-model-len 16384 \
  --port 8000
```
(Use whatever the actual AWQ/GPTQ repo id is; adjust --quantization to gptq_marlin for GPTQ.)

**Option B — FP8 (~27GB, higher quality, tight on VRAM, lower batch size):**
```
vllm serve Qwen/Qwen3.8-27B \
  --quantization fp8 \
  --gpu-memory-utilization 0.92 \
  --max-model-len 8192 \
  --port 8000
```

Verify:
```
curl http://localhost:8000/v1/models
```

Notes:
- Lower `--max-model-len` frees VRAM for more concurrent requests; raise it if you
  need long context and can spare memory.
- vLLM's native quant paths are AWQ/GPTQ/FP8. GGUF support exists but is not the
  fast path — prefer AWQ/GPTQ/FP8 here.

## 2. Install the MCP server

```
cd local-llm-mcp
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## 3. Register with Claude Code

```
claude mcp add local-llm -- /path/to/local-llm-mcp/.venv/bin/python /path/to/local-llm-mcp/server.py
```

To point at a different backend or model, set env vars in the registration:
```
claude mcp add local-llm \
  -e VLLM_URL=http://localhost:8000/v1 \
  -e VLLM_MODEL=Qwen/Qwen3.8-27B-AWQ \
  -e LLM_MAX_CONCURRENCY=16 \
  -- /path/to/.venv/bin/python /path/to/local-llm-mcp/server.py
```

Then in Claude Code, `/mcp` should list `local-llm` with the three tools. Ask
Claude to "use the local-llm generate_batch tool to summarize these files" and it
will fan the work out to the 27B.

## Use against Ollama instead

```
claude mcp add local-llm \
  -e VLLM_URL=http://localhost:11434/v1 \
  -e VLLM_MODEL=qwen3.8:27b \
  -- /path/to/.venv/bin/python /path/to/local-llm-mcp/server.py
```
(Ollama serves sequentially, so batch throughput will be far lower than vLLM.)
