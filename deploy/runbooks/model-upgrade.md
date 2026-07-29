# Model upgrade runbook

Doc 09 §3: "model upgrade = new endpoint + eval suite pass + traffic
switch." This is the blue/green shape applied to this repo's actual
pieces (`config/models.yaml`, `evals/`, Ollama).

## Why blue/green, not in-place

Swapping a model in-place (pulling a new tag over the old one, or editing
`config/models.yaml` and restarting) means the first real request against
the new model is also the first *test* of it — no eval gate, no rollback
path faster than re-pulling the old model. Blue/green means the new
model is loaded and eval-passed *before* any real task ever reaches it.

## Steps

1. **Pull the candidate model into Ollama without touching config**:
   ```bash
   docker exec deploy-ollama-1 ollama pull <new-model-tag>
   ```
   This doesn't affect anything — nothing in `config/models.yaml` points
   at it yet, so no agent will use it.

2. **Point a throwaway eval run at the candidate**, not the live config.
   `evals/awp_evals/harness.py` dispatches real `TaskEnvelope`s and checks
   real outcomes; run the relevant red-team/eval corpus (`make
   redteam-live`, `scripts/resume_extraction_eval.py` for HR-1 extraction,
   `scripts/codeassist_eval.py` for OPS-1 CodeAssist) against a copy of
   the relevant agent's `main.py` env with `MODEL_GEN`/`MODEL_SMALL`
   overridden to the candidate tag, or a scratch script that constructs
   an `LLM` client directly against the candidate model and runs the same
   fixtures those scripts already use. There is no separate "blue"
   environment/container set in this dev compose file (that's real
   infra work a production deploy would add — a second `hr1-canary`
   service pointed at the candidate model, load-balanced or manually
   routed for a subset of traffic); this dev-scale build's equivalent is
   running the eval corpus against the candidate before flipping config,
   not a live traffic split.

3. **Compare against the current model's last known-good eval numbers**
   (see the relevant `DEVIATIONS.md` entry — #18's extraction F1 number,
   #21's CodeAssist live results, #23's red-team pass/fail — for what
   "known good" means for that model's usage). A regression is a reason
   to stop, not a reason to average it out against "it's probably fine."

4. **Traffic switch**: once the eval gate passes, edit `config/models.yaml`
   (and/or the relevant agent's `MODEL_GEN`/`MODEL_SMALL`/`MODEL_CODE` env
   var in `docker-compose.dev.yml`) to the new tag, then `docker compose
   up -d --build <affected agents>`. This is a config change + rolling
   restart, not a code deploy.

5. **Keep the old model pulled** (`ollama list` to confirm) for at least
   one full observation window after the switch — rollback is "point
   config back at the old tag and restart," which only works if the old
   model is still resident.

## Rollback

Revert `config/models.yaml` / the env var override to the previous model
tag, `docker compose up -d --build <affected agents>`. There is no
automatic rollback trigger (no SLO-breach-triggers-rollback automation
exists in this build) — a human decides based on Grafana's `AWP / LLM`
dashboard (error rate, p95 latency by model) and the eval numbers above.
