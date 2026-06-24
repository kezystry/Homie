---
tags: [homie, component, built]
---

# Remember

`core/remember.py` — Behavioral Analysis, the **heart** of the [[Spine]].

Builds a pattern of life from the event stream and answers *"what is normal?"* for a
given topic, zone, and time. The model is deliberately small: per `(topic, zone)` it
counts observations into hour-of-day buckets and tracks distinct days, yielding a
per-day **rate** and a **novel** flag.

- Bootstraps from the [[Bus]] durability log (snapshot + tail) and updates live.
- **Lightweight by design** — it's integer counting; it runs on the Pi 24/7 for free.
  This is why continuous learning is the always-on floor (see [[Always-on topology]]).
- **Evaluate-then-learn**: a consumer that both judges and learns from an event must
  judge first, or the event masks its own novelty.

[[Reason]] and **Security** consume it (via `ctx.recall`); thresholds/policy live in the caller.
