# Owner decisions — 2026-06-27 interview

The owner's answers from a long Q&A. This is the durable record of *what Homie should be for
this household* — read it alongside `docs/MASTERPLAN.md` (engineering plan) and the plain
plan in chat. Where an answer changes a prior assumption, this file wins.

## Household & space
- **Two residents:** the owner (upstairs — has a PC + camera) and his **mother** (downstairs,
  her own flat).
- **Mum's flat is OFF-LIMITS.** No camera, no presence, no representation at all. Homie may
  only be aware of the **front door** and the **owner's upstairs entrance** — nothing more.
- Mum **controls nothing** for now (she doesn't need to); not an operator.

## Machines (tiered, confirmed)
- **Big PC w/ RTX 3060 (12 GB)** = the heavy "brain". Runs **on-demand**; kept in **sleep
  (suspend-to-RAM)** so it wakes fast (seconds), woken by the mini PC (Wake-on-LAN) when deep
  reasoning is needed, then sleeps again. Currently also holds the USB cam.
- **Mini PC** = always-on **passive floor**: keeps things running when the big PC sleeps;
  **runs Home Assistant** and the lightweight Homie floor.
- **Raspberry Pi (+ AI hat, soon)** = privacy-edge **camera** node; becomes the main cam.

## Home Assistant — USE IT, to the max
- **Decision: adopt Home Assistant** as the device/IO layer and lean on it fully. Homie was
  already built to speak HA (the `HomeClient` seam + `deploy/act_map.toml` `light.tradfri_*`).
- **Division of labour:** HA = eyes/ears/hands/phone (device integrations incl. **IKEA
  DIRIGERA** hub + Tradfri bulbs, scenes, **routines/automations**, dashboards, **Companion-app
  phone notifications**, phone-presence device_tracker, **Assist** voice front-end, weather,
  energy). **Homie = the brain** above HA: learns the household, predicts, converses, applies
  friction-learning, drives HA back.
- Light path: **Homie → Home Assistant → DIRIGERA → bulbs.** HA owns simple routines; Homie
  owns the learned/adaptive layer. Direct-DIRIGERA stays a fallback if HA is ever dropped.
- HA runs on the **mini PC** (must work while the brain sleeps).

## The brain (model) — council verdict + owner override
- **Family: Qwen** (unanimous council pick — best tool-calling + good German for mum).
- **Start with Qwen3-8B** (fast, robust, fits 12 GB with headroom); **Qwen3-14B Q4_K_M** as an
  optional "deep-think" upgrade to A/B later. Served by **llama.cpp/llama-server**, GGUF,
  **non-thinking mode**, grammar/JSON-schema-constrained tool decode, low temp, Q8 KV cache,
  capped context, full GPU offload, warm-on-presence.
- **Owner override: use an ABLITERATED model.** Council warned abliteration degrades
  tool-calling/reasoning; mitigation agreed: pick an **abliterated-then-DPO-"healed" Qwen3**,
  **keep the structural safety net** (model stays untrusted; tiles + capability gate enforce),
  and **A/B against stock** so the owner decides by ear.
- **No fine-tuning now** (sparse/noisy friction data makes it worse) — learn via **retrieval
  memory** instead (see GIST below). Revisit QLoRA only with hundreds–thousands of clean,
  validated preference pairs + a plateau on base+retrieval.
- German: Qwen good; SauerkrautLM/DiscoLM-German or Mistral-Nemo as swap-in if German prose
  disappoints in blind tests with the residents.

## Memory — "fresh mind every day" + distilled patterns
- Each **night**: throw away the raw logs, keep only a **tiny distilled memory** of patterns &
  behaviour; the system comes up **fresh, clean, upgraded** each morning.
- The distilled memory is the **GIST format** invented by the research council — see
  `docs/MEMORY-GIST.md`. Learns the owner via **notes the LLM reads**, not retraining.
- **Memory safety:** encrypted at rest + nightly wipe of sensitive bits + a **panic wipe** —
  but **password-REVERSIBLE** ("lock, don't lose"). **Backups:** start with an **encrypted
  local backup** (so a disk failure ≠ total loss); lean toward ephemeral/patterns-only later.
- Hard rule reflected in the format: it can only hold schemas/glyphs/decayed numbers — **never
  raw faces/audio/identifiers**; mum's flat is unrepresentable by absence.

## Voice & interaction
- **Wake-word only** ("Hey Homie") — not passively listening (privacy, esp. mum).
- Owner talks via **voice + typing (phone/terminal) + a TV/PC screen**. (HA **Assist** can be
  the mic/speaker front-end, routing thinking to Homie.)
- **Personality:** short & factual to start; it **learns the owner's preferred tone over time**
  and adapts. (Name: still "Homie" unless owner picks another.)

## Identity (who's who)
- Tell apart **owner / mum / stranger** using **face + voice + phone**, layered (phones for
  presence; faceprints/voiceprints stay on-device, never meshed).

## Alerts / how Homie reaches the owner
- **Phone notification** when away — via a **self-hosted/private notifier** (HA Companion app
  fits; the "safe, local" path), **spoken aloud + on-screen only when he's home**, and
  **always logged** for later.
- **Entrances:** **flag strangers** and speak up **only if something's clearly wrong** —
  otherwise quiet (no chatty who-comes-and-goes log by default).

## Online / privacy posture (hard rules)
- **Never go online without asking** · **nothing ever leaves the machines.**
- Online policy: **pre-approve some uses** (e.g. weather), **ask for the rest**, and **once
  smart enough, decide for itself**. When online, do it **safely** (Brave / VPN / Tor-onion).

## Dream features (the long game) — priority order the owner gave
1. **Weather** (local; into mornings/routines) and **predict the owner's routines** — first.
2. **DHL parcel tracking** (needs limited, approved online).
3. **KartenWerk** — the owner's **Pokémon-card business**; a business-organizer tile
   (inventory/orders/pricing/grading; marketplaces like Cardmarket/eBay later).
4. **Camera vision / "human reading"** (posture, micro-reactions, eventually deception cues) —
   acknowledged as a *years-deep north star*, on the Pi+AI-hat track, **separate** from the
   language brain. Near-term cam = presence/stranger-flagging at entrances only.

## Already built this session (for continuity)
- Plan steps shipped through **M5** (295 tests) + a **box update channel** (`scripts/update.py`,
  pull→health-check→restart) — see `docs/PROGRESS.md`.

## M7 interview — the Dream Journal & privacy guard (2026-06-27)
- **Dream Journal = BOTH surfaces.** (1) A **morning recap** — a short plain-language note of
  yesterday ("Tuesday. Out 9–6. Stayed quiet, lit the kitchen at dusk, you corrected the
  hallway"). (2) An **anytime "what Homie knows about me" page** — every routine/preference it
  currently believes, in plain words, **correctable** (ties to the trust screen + `memory.overlay`).
- **Proactivity = ask-once-then-act, growing to autonomous.** When confident about a routine,
  Homie **offers** to act ("want me to warm the lights at 7?"); on a yes it does it automatically
  thereafter — **until it's smart enough to decide on its own** (the autonomy ladder; gated, never
  a silent new device power without the owner's yes).
- **Unknown person at a watched entrance (front door / upstairs entrance only) = log-quietly,
  speak-only-if-odd.** Keep a quiet log of every unknown for later review; **speak up only when the
  timing/pattern is genuinely unusual or clearly wrong** (options 2+3 combined). Never a chatty
  who-comes-and-goes feed. Mum's flat remains OFF-LIMITS (no camera, no presence, unrepresentable).

## Still open / to confirm later
- The owner's interview is captured; remaining specifics (exact DHL access, KartenWerk
  marketplace APIs, day-type calendar for memory, half-life tuning) are deferred to their tiles.
