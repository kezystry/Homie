---
tags: [homie, component, partial]
---

# Reason

`core/reason.py` — the local LLM decision. Weighs *now* (a live event) against
*normal* (from [[Remember]]) and decides what, if anything, to do. Runs on the
RTX 3060 in the [[Always-on topology|on-demand cortex]]; nothing leaves the network.

- **Proposes, never drives.** It calls tile functions or speaks; the [[Bus]]
  arbitration and per-tile permissions stay the safety floor. The model is
  **abliterated/uncensored** — safety is *structural*, not behavioral.
- **Tool-calling** — `Supervisor.tool_catalog()` exposes tile `functions` (with
  param schemas) as OpenAI-style tools. `validate_tool_call()` is a structural gate
  (unknown name / bad args rejected) before any tile runs. *(built)*
- **Wake gate** — the heavy model wakes only on **novelty + when addressed**; the
  cheap path handles the normal 95%. *(decided; decide()-loop not yet built)*
- **Autonomy** — mixed by risk; bigger actions ask via [[Consent and Gestures]].

Served via llama.cpp/Ollama (8B abliterated, Q5_K_M) over an OpenAI-compatible endpoint;
fine-tuned with QLoRA from friction signals.
