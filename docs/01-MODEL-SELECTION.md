# 01 — SLM Selection, Serving & Fine-Tuning Strategy

**Scope:** Which open-source Hugging Face models power each agent, how they are quantized and served locally, and when/how to fine-tune per department.

---

## 1. Requirements the models must satisfy

1. Runs on one 24 GB GPU **or** Apple Silicon 32 GB+ **or** CPU-only fallback (3B class).
2. Strong native **function/tool calling** (JSON tool schemas) — non-negotiable, agents are tool-driven.
3. ≥ 32k context (RAG over policies, resumes, ledgers, ticket threads).
4. Permissive license for internal commercial use (Apache-2.0 / MIT / Llama community license acceptable for internal use).
5. Good structured-output reliability (JSON mode / constrained decoding via vLLM `guided_json` or llama.cpp grammars).

## 2. Recommended model pool

> Verify latest checkpoints on Hugging Face at build time; the families below are stable, well-supported choices. Swap-in newer minor versions of the same family freely — the architecture is model-agnostic behind an OpenAI-compatible endpoint.

### M-GEN — General department reasoning (primary workhorse)
- **Default:** `Qwen/Qwen2.5-7B-Instruct` (Apache-2.0, 128k ctx, excellent tool calling, strong multilingual incl. Hindi/English mix common in Indian business docs).
- **Alternates:** `meta-llama/Llama-3.1-8B-Instruct` (community license), `mistralai/Ministral-8B-Instruct-2410`, `google/gemma-2-9b-it` (weaker tool calling — needs ReAct prompting).
- **Quantized artifacts:** AWQ 4-bit for vLLM (`Qwen/Qwen2.5-7B-Instruct-AWQ`) or GGUF Q4_K_M for llama.cpp/Ollama.

### M-CODE — Operations coding assistant
- **Default:** `Qwen/Qwen2.5-Coder-7B-Instruct` (Apache-2.0; repo-level completion, FIM support).
- **Alternates:** `deepseek-ai/deepseek-coder-6.7b-instruct`, `bigcode/starcoder2-7b` (completion-only; pair with M-GEN for chat).

### M-SMALL — Router/classifier/extractor (cheap, high-QPS)
- **Default:** `Qwen/Qwen2.5-3B-Instruct` (research license — check; if a hard blocker use `microsoft/Phi-4-mini-instruct`, MIT) for: intent routing in ORCH-0, ticket classification in SUP-1, resume field extraction in HR-1.
- Runs comfortably on CPU (GGUF Q4) at ~15–25 tok/s on a modern 8-core.

### M-EMB — Embeddings (RAG)
- **Default:** `BAAI/bge-m3` (multilingual, dense+sparse+colbert hybrid, 8k ctx) — best for mixed English/Hindi resumes and policy docs.
- **Lighter:** `nomic-ai/nomic-embed-text-v1.5` or `sentence-transformers/all-MiniLM-L6-v2` (CPU-cheap for dev).

### M-RERANK (optional, Phase 2+)
- `BAAI/bge-reranker-v2-m3` — improves shortlisting precision in HR candidate search.

## 3. Serving architecture

```
model-gw (nginx) :8000  ── OpenAI-compatible /v1/chat/completions, /v1/embeddings
   ├── vllm-gen   :8001  M-GEN  (AWQ, gpu-memory-utilization=0.55)
   ├── vllm-code  :8002  M-CODE (AWQ, gpu-memory-utilization=0.35)  [Phase 3]
   ├── llamacpp-sm:8003  M-SMALL (CPU, GGUF Q4_K_M)
   └── tei-emb    :8004  M-EMB  (text-embeddings-inference, CPU or GPU)
```

- **Linux + NVIDIA (recommended prod):** vLLM ≥ 0.6 with `--enable-auto-tool-choice --tool-call-parser hermes` (Qwen) and `--guided-decoding-backend outlines` for JSON.
- **Mac/dev:** Ollama or llama.cpp server; identical client code (OpenAI SDK, `base_url` swap).
- **Routing rule in agent runtime config:** each agent declares `model_binding: {planner: M-GEN, extractor: M-SMALL, coder: M-CODE}`; the gateway maps names → ports.

### Sampling defaults (per task type)
| Task | temp | top_p | max_tokens | JSON forced |
|---|---|---|---|---|
| Tool-call planning | 0.1 | 0.9 | 1024 | yes (tool schema) |
| Classification/routing | 0.0 | 1.0 | 128 | yes (enum) |
| Drafting (emails, JDs, reports) | 0.6 | 0.95 | 2048 | no |
| Extraction (resume/invoice fields) | 0.0 | 1.0 | 1536 | yes (Pydantic schema) |
| Code generation | 0.2 | 0.95 | 4096 | no |

## 4. Context & memory policy

- Hard prompt budget per call: 12k tokens (leave headroom under 32k for tool results). RAG returns top-6 chunks × ≤600 tokens, reranked.
- Long ticket/project threads: rolling summary maintained by the agent (`thread_summary` field updated every 10 messages by M-SMALL).
- No cross-department context leakage: RAG queries always filtered by `department_scope` + row-level ACL tags.

## 5. Fine-tuning path (Phase 3, only if evals demand it)

Do **not** start with fine-tuning. Order of escalation when an agent underperforms:
1. Prompt/few-shot fixes → 2. Better retrieval (chunking, reranker) → 3. Constrained decoding → 4. **LoRA per department**.

**LoRA recipe (when justified):**
- Base: M-GEN. Method: QLoRA (4-bit NF4) via `trl` + `peft`; r=16, alpha=32, target `q,k,v,o,gate,up,down` proj; lr 1e-4 cosine, 2–3 epochs.
- Data: 500–3,000 curated task transcripts per department, harvested from the audit log (approved outcomes only), formatted as chat+tool-call traces. PII scrubbed by the redaction pipeline before training.
- Serving: vLLM multi-LoRA (`--enable-lora`) so one base model hosts `lora-hr`, `lora-finance`, etc., selected per request by header — this is how "a model per department" is realized without 5× VRAM.
- Eval gate before deploy: dept-specific eval suite (doc 09 §6) must improve ≥5 pts with no regression on tool-call validity (>98%) and safety suite.

## 6. Licensing checklist (record in `MODELS.md` of the repo)
For each deployed checkpoint: name, revision hash, license, quantization, eval score snapshot, date. Re-verify license terms whenever swapping checkpoints.
