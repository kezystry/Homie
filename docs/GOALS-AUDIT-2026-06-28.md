# Goals audit — everything you asked for vs. where it stands (2026-06-28)

*A complete pass over every goal and feature the owner has named — across the
[vision interview](VISION-INTERVIEW-2026-06-27.md), the [decisions](DECISIONS-2026-06-27.md),
the [brainstorm](audits/2026-06-27-brainstorm-for-review.md) + its [audit](audits/2026-06-27-brainstorm-external-audit.md),
and the live chat — mapped to what is **built**, **planned**, **deferred on purpose**, **blocked
on hardware**, or **fell through the cracks**. The point is to lose nothing and sharpen the plan.*

**Legend:** ✅ built & working · 🔜 planned (near-term) · 🅿️ deferred by design (waits for a real
trigger) · 🧱 needs hardware · ⚠️ **GAP — wanted but not tracked anywhere** · 👤 owner decision/action.

---

## The headline

You named a *huge* surface (guardian + companion + butler + second brain + a self-improving,
human-reading future). The discipline we agreed (the audit) is: **build the six-thing soul first,
live with it, let real gaps authorise the rest.** That's holding. The big change since we wrote the
plan: **the physical layer is now LIVE** (HA + DIRIGERA + all bulbs + Homie driving them), which
promotes a few things from "someday" to "now" — see *Improvements* at the end.

In shape (not made-up precision — just honest buckets): **the "knows-me" soul is largely built**;
**a focused set is planned next** (undo + autonomy + the calendar/weather wiring); **the big pillars
are deliberately deferred** (full guardian, business/KartenWerk, vision, self-upgrade) until the soul
is lived-in; and **a handful of wants had slipped through with no home** — now caught below.

---

## 1 · The soul — "knows me" + effortlessness (your #1)
| You wanted | Status | Notes |
|---|---|---|
| Knowing me deeply | ✅ | honest-belief model + "What Homie Knows" page |
| Morning recap (yesterday) | ✅ | `core/recap.py`, capped, honest |
| Day briefing (today, what's on, route) | ✅ | `core/agenda/briefing/route.py` — your add, council-designed |
| Effortlessness / never a nag | ✅ | a self-pacing voice — **learns** how chatty to be from your reactions (muting shrinks it), no hand-set cap + a mute |
| Adaptive personality (humor vs minimal) | 🅿️ | designed as render-time "ToneState"; deferred (apparatus) |
| Secret/personal name + duress anti-name | 👤 🅿️ | **now a password** (owner-only, hash-verified, never stored/logged; the spoken-in-chat unlock idea is retired) — you set it |
| "Feel alive" / anticipates perfectly | 🅿️ | AliveState + silent-anticipation designed; after the basics |
| First-magic: right thing before I ask | 🔜 | comes with Phase E autonomy (offer→silent) |

## 2 · Daily rhythm & interaction
| You wanted | Status | Notes |
|---|---|---|
| Gentle silent morning + proactive brief on work days | ✅ | briefing is work-day-gated, silent otherwise |
| "Welcome back — anything you need?" on arrival | 🧱 | needs presence/phone-arrival signal |
| Ask-when-unsure, confident on clear patterns | 🔜 | the autonomy ladder (Phase E) |
| Inputs: screen + typing + voice wake-word + "it just acts" | ◑ | chat/screen ✅; **voice (wake-word) not built** ⚠️→tracked below |
| Best local voice (TTS) | ⚠️ 🧱 | named, never tracked — needs a voice/Assist stack |
| Reach me on my phone (app + web + messaging) | ◑ | **HA Companion app already gives push + remote** ✅; a Homie-native channel later |
| Subtle ambient orb (only if perfect) | 🅿️ | quality-gated |

## 3 · Guardian / security (trust-earner #4)
| You wanted | Status | Notes |
|---|---|---|
| Active network/presence security watch | 🅿️ | NetSense alert-only, deferred |
| Full-deterrence intrusion (lights+alarm+record+alert+police) | 🅿️ | GuardianLoop designed; high-stakes → lands later |
| Emergency calls (confirm-first, auto only on no-response) | 🅿️ 👤 | two-key rule designed; you set the window |
| Active cyber-defense (block/quarantine) | 🅿️ | alert-only first; teeth earned over months |
| Hazard sensors (smoke/CO/water/gas) | 🧱 | integrate the ones you have, when wired |
| Mum's welfare at the boundary (front door + your entrance only) | 🅿️ 🧱 | hard privacy fence designed; needs the door cam |
| Mum's flat OFF-LIMITS, unrepresentable | ✅(by design) | enforced as a construction rule in the spec |

## 4 · Memory & transparency
| You wanted | Status | Notes |
|---|---|---|
| Years of distilled wisdom, no raw history | ◑ | 30-day model ✅; the durable "wisdom tier" 🔜 |
| Live day = full, next day = GIST | 🔜 | nightly fold exists; GIST distillation slice pending |
| Pin & forget (forever / erase everywhere) | 🔜 | tied to the correction overlay + undo |
| Nightly "what changed/improved" note | 🔜 | the recap's "Tidied" beat (needs the nightly fold to compose it) |
| Full transparency of what it learned | ✅ | the "What Homie Knows" page |
| Encrypted at rest + nightly wipe + panic/duress wipe (reversible) | ◑ | **LUKS full-disk ✅**; panic-lock + duress-wipe 🅿️ |
| Layered backups (local + cross-machine + cold) | 🅿️ | MemoryBundle designed; encrypted-local first when built |

## 5 · Autonomy ladder (earns trust step by step)
| You wanted | Status | Notes |
|---|---|---|
| Earns autonomy, tight leash → trusted | 🔜 | Phase E: hand-set rungs + auto-demote-on-reversal |
| First solo: lighting + climate | 🔜🧱 | lighting buildable NOW (dusk); climate needs a thermostat |
| Most guarded: irreversible + money (always ask) | 🔜 | a permanent GUARDED list |
| Self-proposing automations (I approve) | 🅿️ | after the ladder exists |
| Full timeline undo + correction log | 🔜 | **Phase D — the next build** |
| A real yes/no confirm (`confirm.response`) | 🔜 | Phase D prerequisite (audit said: jumps the queue) |
| Off switch + one-tap guest mode | 🅿️ | master controls, Phase visible-posture |

## 6 · Butler / life-admin & business (trust-earner #3)
| You wanted | Status | Notes |
|---|---|---|
| KartenWerk: inventory, pricing, orders/shipping, grading, deal-spotting | 🅿️ | your business — a major future pillar, deferred till the soul is lived-in |
| Market watch / deal alerts | 🅿️ | recap-only digest first, behind the speech budget |
| Parcels/deliveries (DHL) | 🅿️ 👤 | needs approved online + a login |
| Bills/appointments | 🔜 | flows into the Agenda (calendar/todo already wire in) |
| Second brain / notes | 🔜 | a plain notes tile feeding the Agenda |
| Draft + send messages in my style (buying/selling always approved) | 🅿️ | the "Outbox" (draft→swipe), money-gated |

## 7 · Online & the world (hard rules)
| You wanted | Status | Notes |
|---|---|---|
| Never online without asking · nothing leaves the machines | ✅(policy) 🅿️(enforced) | the rule holds; the **EgressGuard** chokepoint is designed, not built |
| Pre-approve weather / card-prices / lookups | 🔜 | weather wires into the briefing next |
| Private (VPN/Tor) for sensitive, direct for trivial | 🅿️ | with the egress work |
| Cloud AI only anonymised, brain stays local | 🅿️ | local-only today (no cloud calls at all) |

## 8 · The brain (model)
| You wanted | Status | Notes |
|---|---|---|
| Reliability over speed | ✅ | serving discipline (latency SLO, warm/cold) |
| Abliterated-then-healed model, structural safety net | ✅(design) 🧱 | model card + the never-trust-the-model architecture; **GPU brain not stood up yet** |
| Start on the 3060, stronger HW later | 🧱 | the desktop is the cortex node; LLM serving is the next hardware bring-up |
| Fine-tune to me, carefully, eventually | 🅿️ | retrieval-memory first; QLoRA only on evidence |

## 9 · Self-evolution (your bold ask, with rails)
| You wanted | Status | Notes |
|---|---|---|
| Nightly self-upgrade, always-latest | 🅿️ | M11 — split into free-data-drift vs gated-code |
| Self-coding with tests + rollback | 🅿️ | signed pipeline + atomic rollback designed |
| Broad-internet updates with checks | 🅿️ | as untrusted data, never bypassable code |
| Self-heal + roll back to last good + log | ◑ | nightly ritual + update channel exist; full self-upgrade deferred |
| **Signing key OWNER-HELD only (no self-signing)** | ✅(rule) 👤 | locked as binding in SCOPE; you choose key custody later |

## 10 · Comfort, media, delight, sleep
| You wanted | Status | Notes |
|---|---|---|
| Learn ideal climate + pre-warm/cool | 🔜🧱 | Phase E ClimateTile, needs smart heating |
| Energy: report-only | 🅿️🧱 | when there's an energy meter |
| Sleep: actively optimize the environment | 🅿️🧱 | wind-down light/temp, after climate |
| Entertainment butler + music DJ | 🅿️ | media tile, deferred |
| Stremio sandbox risk — research & fix without breaking | ⚠️ | flagged in the plan, **never turned into a task** → tracked below |
| Small delights (rationed, OFF by default) | 🅿️ | after the speech budget is lived-in |

## 11 · Vision / human-reading (the north star)
| You wanted | Status | Notes |
|---|---|---|
| Read people: posture→mood→distress→intent→deception | 🅿️🧱 | explicit years-out north star; on-Pi, gated rung-by-rung |
| Near-term: presence + stranger-flag at the 2 entrances | 🧱 | needs the Pi + camera |
| Medical-event judgment call | 🅿️ | part of the distress rung, far out |
| Gestures only if flawless | 🅿️ | quality-gated |

## 12 · Values, character, what-ifs
| You wanted | Status | Notes |
|---|---|---|
| Never deceive / manipulate / put-anyone-above-me / hide | ✅(rule) 🔜(signed) | the four-nevers CHARTER as signed code |
| Always honest, reads the moment | ✅ | honest-by-construction surfaces (no overclaiming) |
| Mum's safety can override in a genuine emergency | 🅿️ | guardian judgment rule |
| Obedient first, real character eventually | ✅ | obedience floor; tone widens later |
| Worst outcome = a nag | ✅ | the self-pacing voice exists for this — it learns to shut up |

## 13 · Devices / reach / hardware
| You wanted | Status | Notes |
|---|---|---|
| HA + DIRIGERA + all bulbs | ✅ | **done today** — live and driving |
| This home deeply + light mobile presence | ◑ | home ✅; mobile via HA app ✅, Homie-native later |
| Next devices: environment sensors + more cameras | 🧱👤 | **the key unlock** — see Improvements |
| Deep phone integration (calendar, location, messages) | 🅿️ | calendar via HA ✅-ish; location/messages later |

---

## Gaps that were slipping (now caught — added to the backlog)
1. ⚠️ **Voice / wake-word ("Homie") + a local voice** — named clearly, never tracked. HA's **Assist**
   can be the mic/speaker front-end → a real near-term option now that HA is live.
2. ⚠️ **Stremio unsandboxed-browser risk** — flagged in the plan and the security review, never a task.
   Small, concrete: research + sandbox/move it before any lock lives on that machine.
3. ⚠️ **Phone notifications path** — turns out **already solved**: you're on the HA Companion app, so
   push + remote access exist today. Homie should *use* it (notify via HA) rather than build its own.
4. ⚠️ **The recap's "Tidied"/"what improved overnight" note** — wanted; needs the nightly fold to
   compose `recap_line`. Tracked as part of Phase B's remaining fold work.
5. ⚠️ **Per-person / guest privacy + mood-learning** — both blocked on one unfinished wire (the
   reconciler `context`: actor/zone are `None` today). Landing that one wire unblocks a cluster.

## Improvements to the plan (what the live device layer changes)
- **Promote automatic lighting to NEXT, alongside Phase D.** It's now buildable (dusk on/off, no
  sensors) and is your fastest real "it's alive" moment — disproportionate payoff for the effort.
- **Elevate "a presence/motion sensor or two" to the top of the hardware list.** It's the single
  unlock for the autonomy ladder, "welcome back", mood, and proper room-lighting — more wants depend
  on it than on anything else. (IKEA sensors pair into your DIRIGERA → appear in HA like the bulbs.)
- **Use HA Assist for voice and HA Companion for notifications** instead of building Homie-native
  versions now — two big wants become near-free because HA is already running.
- **Keep the build order:** Phase B-finish (nightly fold + day-type) → **Phase D (undo + confirm)** →
  **Phase E (lighting/climate autonomy)** → then live with it a month before opening the butler/
  guardian/vision pillars. The audit's discipline stands; the device layer just made D/E more real.

## Owner decisions still open (no rush)
- 👤 Secret name + duress anti-name (you set these).
- 👤 Buy a **motion/presence sensor**? (unlocks the most).
- 👤 Emergency-call confirm window + "unmistakable" bar (far off).
- 👤 Self-upgrade signing-key custody: phone vs hardware token + a backup signer (far off).
- 👤 KartenWerk: which marketplace, when to start (after the soul is lived-in).
