# Owner preferences — decisions captured 2026-06-28

The owner answered a 30-question intake (a 3-agent council generated the last 20). These are
binding product defaults until changed. They shape config and roadmap; they are NOT all built
yet. Camera/recognition items are recorded only — **nothing in the camera direction is built
until the owner has a Hailo-8** (standing constraint).

## Hardware & deployment
- **Owns now:** Mini-PC (Home Assistant anchor), RTX-3060 desktop (**Homie-OS only — no Windows**,
  so the cortex is available whenever the desktop is on), DIRIGERA (IKEA Zigbee) hub.
  **No Pi 5, no Hailo, no Zigbee dongle yet** (SONOFF Zigbee/Thread PoE **Dongle Max** on the
  shopping list, `docs/PLAN.md`).
- **Anchor uptime:** best-effort (systemd auto-restart + watchdog; no UPS).
- **Perception:** validate the whole **software loop first** (synthetic perception); buy Pi+Hailo
  once stable. Save the ~€300 until then.
- **Location:** Germany. Current **54.34732° N, 10.21823° E**; moving to **54.39941° N,
  10.22457° E** next week (Tue–Fri). On the move: **shut down, move, restart, update coords.**
  `HOMIE_TZ=Europe/Berlin`.
- **HA control:** DIRIGERA **already connected to HA** (IKEA bulbs drivable today). Migrate/extend
  HA-native once the Dongle Max arrives.
- **HA-down fallback:** failsafe — everything auto-restarts, self-heals; "dumb hand" while down is
  acceptable. Physical switches always work.
- **Self-upgrade:** **nightly auto** (pull → test → rollback-if-bad → restart when undisturbed) —
  the M11 routine as shipped.

## Control & autonomy
- **May auto-drive:** everything **except locks / garage / alarm** (the guarded domains).
- **Autonomy pace:** **conservative from day 1** — lights/climate auto now; guarded + irreversible
  always ask.
- **Guarded confirm:** a **spoken "yes" is enough** (never inferred, never earned away to silent).
- **Welcome proactive behaviours (all):** arrival/dusk lighting · tonight's watch pick · morning
  briefing · genuine unusual-event alerts.

## Memory & media
- **Memory depth:** **deep companion model** is the goal — learn preferences/moods/stress over time
  and adapt. (Build up to it; start honest and slow.)
- **Watch learning:** **full taste fingerprint** — track how taste evolves + rewatch patterns, not
  just time-slots.
- **Recommendations surface:** a **Homie cockpit pane** (continue / tonight's pick / rewatch).
- **Morning word:** **both text + spoken, always** (spoken needs TTS on the 3060 — future wiring).

## Personality & speech
- **Tone:** **pure assistant for now** → once it has genuinely learned him, **adapt into an
  efficient companion**. (Personality is render-time; evolves, never baked in.)

## Privacy & people  *(recorded only — camera work paused until Hailo)*
- **Recognition:** **always identify people**, but **store NO real photos** — identity is a
  **label/remark** only. When unsure who someone is, **ask the owner via a text message to his
  phone** (his **main private channel when others are present**); the owner's reply sets the label.
- **Unknown person:** **text-message the owner** to ask; otherwise stay silent unless a genuine
  threat.
- **Master OFF switch:** **all three** — chat `/command`, voice command, and a **two-stage
  `/panic` (reversible) + `/wipe` (irreversible, countdown)**.
- **Guest mode:** **silent learning** — keeps learning, never speaks or shows it while on.

## New capability this intake surfaced (future, not built)
- **Phone text channel** as Homie's private back-channel to the owner (identity asks, unknown-person
  alerts, the off/guest controls). Likely an HA `notify` target (e.g. ntfy/Telegram/Signal) — to be
  designed when perception/recognition is built (post-Hailo).
