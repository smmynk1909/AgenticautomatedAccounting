# Degraded CPU / host-capacity mode

This runbook exists because of a real incident, not a hypothetical one —
see `DEVIATIONS.md` #19's third update and #20's second update for the
full account. Recorded here so the next person (or the next session)
recognizes the symptoms in minutes instead of an afternoon.

## Symptoms

- `docker ps` / any `docker` command takes 30s-150s+ or times out, even
  though `docker compose ps` a minute earlier looked fine.
- `docker exec` calls into a specific container return `request returned
  500 Internal Server Error ... dockerDesktopLinuxEngine` — this is the
  Docker Desktop API itself, not one container's networking.
- Containers stay `Up` throughout (check `RestartCount`/`OOMKilled` via
  `docker inspect` if you can get a command through) — this is *not* a
  crash-loop. That distinction matters: if containers are actually
  restarting, this runbook doesn't apply; look at that container's own
  logs instead.
- A container-to-container call fails with `UpstreamError: ... unreachable:
  [Errno -3] Temporary failure in name resolution` — Docker's internal DNS
  degrading under host resource pressure, not a real network-config bug
  in this repo.

## Root cause (confirmed, not guessed)

This stack is CPU-inference-heavy (Ollama, CPU-only per `DEVIATIONS.md`
#1) and container-count-heavy (24+ services). On a host with headroom
below roughly 32GB RAM, the WSL2 VM backing Docker Desktop alone can hold
~8GB at idle with this compose file up, before any LLM call runs. One
concurrent CPU inference call can drop free host memory to 1.5-2GB, at
which point Docker Desktop's own control-plane API — not just the
containers it manages — starts failing.

## Fix, in order

1. **Full Docker Desktop + WSL2 restart** (not just `docker compose
   restart`): stop `Docker Desktop`/`com.docker.*` processes, then `wsl
   --shutdown`, then relaunch Docker Desktop. This reliably reclaims the
   memory a `docker compose restart` alone doesn't (the VM itself, not
   just the containers, is holding it).
2. **Prune stale build cache**: `docker builder prune -f && docker image
   prune -f` — cheap, sometimes reclaims double-digit GB of *disk* (not
   RAM, but worth doing while you're in here).
3. **Stop non-essential containers** for whatever you're actually trying
   to do. Example: verifying an HR-1 or OPS-1 flow doesn't need `gitea`,
   `mcp-search`, `mcp-docs`, `mcp-finance`, `mcp-hrsourcing`, the other
   five agents, `scheduler`, or `qdrant` running. In practice this
   recovers less RAM than you'd expect (these are small Python services;
   the WSL2 VM and Ollama are the real consumers) but it does reduce
   *contention* — fewer processes competing for the same CPU cores.
4. **If none of the above resolves it within a few minutes**: stop. Don't
   keep retrying commands against an already-strained daemon — each
   attempt adds load to a system that's already thrashing, and (confirmed
   this session) can eventually degrade to whole-machine unresponsiveness
   where even unrelated shell commands hang. Escalate to a host-level fix
   (see below) instead of continuing to push through the application
   layer.

## Real prevention, not a workaround

- **Run this stack on a host with more RAM.** 32GB+ is the realistic
  floor for comfortably running the full compose file plus CPU inference
  plus normal dev tooling at the same time; 16GB is workable for a
  trimmed subset (see step 3 above) but not the full stack under load.
- If GPU inference becomes available (doc 01's real target — Ollama-on-
  CPU is `DEVIATIONS.md` #1's deviation, not the design), the CPU/RAM
  pressure this runbook is about mostly goes away — VRAM absorbs the
  model weights instead of host RAM, and inference no longer competes
  with Docker's own control plane for CPU cycles.
- `.wslconfig` (`%UserProfile%\.wslconfig` on Windows) can cap the WSL2
  VM's memory ceiling explicitly, trading "never eats all host RAM" for
  "may OOM inside the VM instead" — a deliberate choice for a shared dev
  machine, not done by default here since it wasn't asked for and the
  right ceiling depends on the host's total RAM.
