# Homie's brain — model card & serving (M6)

This is the heavy reasoning model: an 8B served on the RTX 3060 desktop, woken on demand
and kept asleep otherwise. It is **untrusted by construction** — every tool call it proposes
is validated structurally against the live catalog and routed through a tile's declared
actuators (`core/reason.py`), and the capability gate (`core/capability.py`) enforces
least-privilege. So the model only has to be *useful*; the architecture, not the model's
manners, keeps it safe. That is exactly what lets us run an abliterated model.

## The decision (owner's call)

- **Default: an abliterated-then-"healed" Qwen3-8B.** Abliteration removes refusal behaviour;
  the council's warning was that it also dents tool-calling/reasoning, so the default is an
  abliterated model that has been **DPO-healed** (re-tuned to recover instruction-following),
  not a raw ablation. Qwen3 was the family pick for its strong tool-calling and decent German
  (for the mother).
- **Keep stock Qwen3-8B served alongside for A/B.** Flip `HOMIE_LLM_MODEL` (and point at the
  matching server) to compare them *by ear* in the real home. The structural safety net holds
  for both, so this is a quality/taste choice, not a safety one.
- **No fine-tuning now.** Learning is via retrieval memory (see `docs/MEMORY-GIST.md`), not
  weight tuning — revisit only with a large, clean preference dataset and a measured plateau.
- A 14B Q4_K_M is an optional "deep-think" upgrade to A/B later if 12 GB headroom allows.

> Pick the specific GGUF on the desktop at bring-up (an abliterated-then-healed Qwen3-8B in
> Q5_K_M is the target). The repo pins the *serving discipline*, not a model file.

## Serving (llama.cpp / llama-server, loopback only)

```sh
# On the 3060 desktop. Q5_K_M ≈ best quality that leaves KV headroom on 12 GB.
llama-server \
  --model qwen3-8b-abliterated-healed.Q5_K_M.gguf \
  --alias homie \                # must match HOMIE_LLM_MODEL
  --host 127.0.0.1 --port 8080 \ # loopback ONLY — nothing leaves the box
  --ctx-size 8192 \              # capped context; the prompt is small (GIST brief + tools)
  --n-gpu-layers 999 \           # full offload to the 3060
  --cache-type-k q8_0 --cache-type-v q8_0 \  # Q8 KV cache: more context per GB
  --temp 0.4 --jinja             # --jinja enables the model's tool-call template
```

Then point Homie at it:

```sh
export HOMIE_LLM_URL=http://127.0.0.1:8080/v1/chat/completions
export HOMIE_LLM_MODEL=homie          # flip to the stock alias to A/B
# export HOMIE_LLM_TEMPERATURE=0.4     # low temp: steadier tool decoding
# export HOMIE_LLM_TIMEOUT=30          # seconds; the GPU is on-box
# export HOMIE_LLM_GRAMMAR=/opt/homie/deploy/reply.gbnf   # optional extra constraint
```

With `HOMIE_LLM_URL` set, `scripts/run.py` brings up the reasoning cortex; unset, the Pi
anchor runs the same graph with no GPU dependency. Both paths are tested.

## Serving discipline (what M6 added)

- **Grammar-constrained tool decoding.** Requests carry the tool schemas and
  `parallel_tool_calls: false`, so llama-server constrains a tool call's arguments to the
  function's JSON-Schema as it samples — a malformed call essentially can't be produced, which
  cuts the distrust-and-drop rejections in `Reason`. An optional GBNF (`HOMIE_LLM_GRAMMAR`)
  can further bound free-form replies.
- **A latency SLO.** Every model call is timed on a monotonic clock and recorded against a
  budget (`core/serving.py` `LatencySLO`); each call emits a `reason.served` event with the
  round-trip latency, whether it met the SLO, and the rolling p95. A brain that has gone slow
  becomes a number on the status page, not a vague feeling. Measurement never changes a
  decision — honesty is free.
- **A warm/cold policy.** `WarmPolicy` keeps the model warm for a window after each real wake
  (widening during a busy stretch, relaxing when activity is sparse) so a flurry of events
  doesn't re-pay the cold-start each time, while letting the desktop sleep when the house is
  quiet — matching the owner's "keep the main PC in sleep for fast wake-up" choice. The
  *mechanism* (Wake-on-LAN, GPU suspend) is the deploy/OS layer; the *policy* is tested here.

## Safety posture (unchanged, and load-bearing)

The model never drives the home directly. It proposes; `Reason` validates; a tile acts only
through its declared actuators; the bus arbitrates by priority; the act-map's `never_touch`
list is an absolute outer boundary. Abliteration changes what the model is *willing* to say,
never what it is *able* to do.
