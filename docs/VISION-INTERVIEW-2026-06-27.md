# Homie — the big vision interview (2026-06-27)

*A long structured interview with the owner to refine the whole Homie idea, feeding a massive
brainstorm. Answers captured verbatim-in-spirit as they come in. This is durable input — read it
alongside `docs/DECISIONS-2026-06-27.md`.*

## Recent decisions carried in (from the prior rounds)
- **Memory: lean now, keep the full GIST design on the shelf.** Build the 3 real statistical fixes
  into the live model + render plain readable notes; defer the codec/HMAC/DP cathedral until a
  requirement names it. (Two independent reviews converged on this.)
- **Encryption: disk encryption (LUKS) is enough for now** — no extra in-app signing yet.
- **Morning recap reaches you: on a screen when home + a phone notification.**
- **Next focus: let a council decide** (folds into the brainstorm).

## Soul (round 1)
- **What Homie is:** *everything* — guardian + companion + butler + second brain, all of it.
- **Personality:** an **adaptive mixture** — smart enough to read when he wants humor vs minimal
  "just yes, working" mode. **For now: always do what he says, no talking back, a little character.**
- **The one thing to be excellent at:** **knowing him deeply.**
- **Whose home brain:** **his alone** (mum protected at the boundary, never an operator).

## Daily rhythm (round 2)
- **Mornings:** mainly a **gentle silent ready-state**; **a proactive brief too on work days** (when
  he has things to do).
- **Arriving home:** **"welcome back — anything you need?"** (asks what he wants).
- **Boldness:** **ask when unsure** (confident on clear patterns, checks on ambiguity).
- **Initiative:** **only if something's wrong + occasionally when genuinely useful.**

## People & identity (round 3)
- **Guests:** **learn them if they recur** + **may quietly ask who** + **check the phone connected to
  the network.** Key principle: **Homie lives in the network as much as on the PC** — network-aware
  presence/identity.
- **Mood:** **yes — learn it and gently adapt** (calmer lights when winding down, fewer interruptions
  when stressed).
- **Mum's welfare:** **if a camera goes on the front door, a mix of "notice if her rhythm seems off →
  flag to him" and "clear emergencies"** — welfare without surveillance, within her hard limits.
- **Presence:** **one signal among several** (phone + door + motion + face + network).

## Red lines & camera (round 4)
- **Absolute red lines:** **never send data off the machines without asking; never watch mum's
  space.** (Notably he did NOT make "never store raw video" a red line — security recording is wanted,
  see below.)
- **Camera:** **may send an image to police or to a display in an emergency**, but **mostly only
  clips/photos stored for security.** So: security recording is in-scope; emergency egress allowed.
- **Network awareness:** **active security watch** (a network guardian).
- **When unsure if something's private:** **ask him.**

## The guardian role (round 5)
- **Intrusion response:** **full deterrence** — lights, alarm, record, alert him, AND prepare police.
- **Emergency services:** **yes, can call — but confirm first if it can** (auto-call only if he
  doesn't respond in the seconds it has).
- **Cyber/network threat:** **active defense** — block/quarantine/isolate and report.
- **Hazard sensors (smoke/fire/CO/water/gas):** **integrate the ones he has, for now.**

## Memory & forgetting (round 6)
- **Reach:** **years, as distilled wisdom** — long-term distilled sense of him across years, no raw
  history. *(So the lean memory must still support a long-term distilled layer, not just a 30d window.)*
- **Pin & forget:** **both** — he can make something stick forever or erase it everywhere.
- **Nightly fresh start:** **visibly refreshed** — a readable "what changed/improved overnight" note.
- **Sensitive learnings:** **full transparency** ("it's only between a local AI and me"); wants to
  build a dedicated privacy feature in the future anyway.

## Memory model clarification (round 8)
- **Live day = full knowledge; next day = GIST.** During the current day Homie keeps EVERYTHING
  (every event, full detail); the nightly fold distils it to GIST for space-saving from the next day
  on. *This reaffirms GIST's role (cross-day distillation) — "lean" means drop the over-engineered
  codec/HMAC/DP, NOT drop the distillation idea.*

## Interface & interaction (round 7)
- **Main input:** **all of it** — screen/dashboard + typing + voice wake-word + "it just acts."
- **Voice style:** **best available local voice; he'll pick the actual voice later.**
- **Remote link (away from home):** **a mix** — private phone app + secure web page + private
  messaging (not app-only).
- **Visible presence:** **just a name for now**; a **subtle ambient indicator (orb)** is appealing
  *only if it's perfect, flowing, really well done.*

## Trust & control (round 8)
- **"What it knows" page:** see above (full live, GIST for past).
- **Undo:** **full timeline undo** — scroll back and reverse anything, anytime.
- **Explainability:** **proactively explain the unusual** (routine stays silent).
- **Master controls:** **a full off switch + a 'guest mode'** (one-tap minimal/extra-private).

## Autonomy ladder (round 9)
- **Autonomy:** **earns it step by step** (tight leash → proven abilities trusted solo).
- **First trusted solo:** **lighting + climate/comfort.**
- **Most guarded, longest:** **anything irreversible + spending money.**
- **Self-proposing automations:** **yes, propose freely** (he approves/declines).

## Business & life admin (round 10)
- **KartenWerk:** **everything** — inventory, pricing/market, orders & shipping, grading & deal-spotting.
- **Market watch:** **track & alert deals** (a steal to buy, a spike to sell into).
- **Life admin:** **all** — parcels/deliveries, bills/appointments, a notes/second-brain, draft messages.
- **Online actions:** **approve each — but with fewer OKs**; once set up correctly it **can text for
  him, in his style (imperfections and all)**; **buying/selling specifically always needs approval.**

## Online & the world (round 11)
- **Pre-approved online:** **weather, card-market prices, info lookups** (parcel tracking left out —
  likely needs a login/approval).
- **Online care:** **private (VPN/Tor) for sensitive, direct for trivial.**
- **Cloud AI:** **only anonymized, non-personal** hard tasks; the personal brain stays local.
- **Web research:** **skeptical — verify & cite sources.**

## Resilience & failure (round 12)
- **Machine dies:** **all** — home keeps basic functions + memory never lost + told immediately.
- **Homie crashes:** **all** — auto-heal + roll back to last good + log what happened.
- **Backups:** **layered** — encrypted local + across machines + an offline cold copy.
- **Worst case (fire/theft):** **encryption as the baseline** (stolen drives useless); remote-wipe /
  off-site backup deferred.

## Camera & "human-reading" north star (round 13)
- **Vision depth:** the **deep dream — read people** (years out: posture → mood → distress → intent →
  deception cues).
- **Most valuable for:** **understanding him.**
- **Medical event:** **judgment-based** — if it's unmistakable (e.g. "bleeding out") **call**;
  otherwise if it can help/fix, **alert him**; broadly "do what's best."
- **Gestures:** **only if flawless** (a janky gesture system is worse than none).

## Comfort, climate, energy, sleep (round 14)
- **Climate:** **learn his ideal + pre-warm/cool to his schedule**, once smart heating/cooling exists.
- **Energy:** **just report usage** for now (don't auto-optimize).
- **Sleep:** **yes — actively optimize** the sleep environment (wind-down light, ideal temp, quiet).
- **Solar/battery later:** **report & suggest** (don't auto-optimize yet).

## Media, mood, delight (round 15)
- **Entertainment:** **suggest & control playback** (a media butler across screens).
- **Movie app (Stremio) risk:** **research whether it's actually a problem; if so, fix it without
  breaking it** (don't assume it's fine, but don't disrupt his media).
- **Music:** **learn & DJ** — play the right thing for the moment.
- **Delight:** **yes, small delights** — occasional thoughtful touches that make it feel alive.

## The brain (round 16)
- **Smartness:** **upgrade hardware later** — start with what fits the 3060, plan stronger HW for a
  smarter brain.
- **Fine-tune to him:** **yes, eventually — carefully** (with rollback), once there's clean data.
- **Brain shape:** **most efficient** (agent's call — leans specialists + a main brain).
- **Speed:** **reliability over speed** — a correct slower answer beats a fast wrong one.

## Self-evolution (round 17) — ambitious; note the safety tension
- **Nightly self-upgrade:** **bold — always latest.**
- **Self-coding:** **yes — it can modify its own code, with full tests + rollback.**
- **Update source:** **broad internet, with checks.**
- **Personality drift:** **freely adapt to him.**
- ⚠ **Tension to resolve in the brainstorm:** bold + broad-internet self-upgrade + self-rewriting
  conflicts with the security reviewer's "signed releases only / human-gated" warning (audit NEW-3).
  The brainstorm must reconcile *aggressive self-improvement* with *strong rails* (sandbox → full
  test gate → signed/verified → auto-rollback → changelog), not pick one.

## Privacy feature & sovereignty (round 18)
- **The privacy feature he wants:** **guest / per-person privacy** (control what's recorded/visible
  when specific people are around).
- **Vault:** **no** — Homie should know everything to help him (it's local and his).
- **Other access:** **decide later** (single-owner for now).
- **Coercion guarantees:** **encryption only he can unlock + a panic/duress wipe.**

## The felt experience (round 19)
- **Feeling he most wants:** **effortlessness** (friction and chores quietly disappear).
- **Presence level:** **somewhere between** — ambient and felt, never intrusive.
- **On mistakes:** **it owns it** — acknowledges, explains, visibly improves (trust the process).
- **Will vs serve:** **a real character eventually** (genuine perspective, still loyal) — but obedient first.

## Growth & reach (round 20)
- **Reach:** **this home deeply + a light mobile presence** when out.
- **Car/travel:** **just stay reachable** (home-focused; alerts when away).
- **Next devices wanted:** **environment sensors + more cameras.**
- **Phone integration:** **deep** — calendar, location, maybe messages → a true assistant.

## Values & character (round 21)
- **Never:** **deceive · manipulate · put anyone above him · hide what it's doing** (all four).
- **Honesty:** **always honest, and reads the moment** (truthful, smart about how/when).
- **Him vs mum:** **mum's safety can override in a genuine emergency**, otherwise his call.
- **Worst thing to prevent:** **a nag that annoys him** → reinforce quiet, low-interruption design.

## Build priorities (round 22)
- **First win he wants:** **"knows-me" — the morning recap + the "what it knows" page.**
- **Deepest trust earner, in order:** **1) never break / always recover, 2) nail my routine unprompted,
  3) save real time/effort, 4) catch a real security event.** *(Reliability is the #1 trust earner.)*
- **Pace:** **balanced.**
- **Councils:** **yes — always for big stuff** (they keep catching real issues).

## Name, vibe, touches (round 23)
- **Name:** **keep "Homie" publicly + a personal/secret name only he uses.**
- **Vibe:** **a mix of all** — dark/techy + sci-fi "The Machine" + warm + nearly-invisible (adaptive).
- **Wake word:** **"Homie".**
- **Acknowledge cue:** **both a subtle sound + a light cue, tasteful** (ties to the ambient orb).

## Hard what-ifs (round 24)
- **Disagreement:** **depends on severity** (trivial → obeys instantly; life-safety → escalates per rules).
- **Incapacitated:** **do what's best to help** (judgment-driven escalation).
- **Self-harm:** **stay out of it** (respect his autonomy).
- **Future kids/family:** **extra protective of them** when present.

## The dream & brainstorm steer (round 25)
- **Invent one capability:** **make the home feel alive** (genuinely responsive, present).
- **First "magic" moment:** **it anticipates perfectly** (the right thing before he asks).
- **Guard hardest against (ALL):** **privacy leaks · breaking/unreliable · getting annoying · over-complexity.**
- **Brainstorm aim:** **refine the vision + roadmap** — with those four worries as hard guardrails.

---

## Throughline (for the brainstorm)
Homie is *everything* (guardian + companion + butler + second brain), but the **soul is "knowing him
deeply"** and the **feeling is effortlessness**. Build order favours **"knows-me" first** and
**reliability as the #1 trust earner**. It must be **bold and self-improving** yet **never a nag,
never a privacy leak, never fragile, never over-complex** — the central tension to engineer. Strong
**guardian** scope (full-deterrence intrusion, active cyber-defense, judgment-based emergency calls)
and an eventual **deep human-reading** north star, all **local, his alone, encrypted, panic-wipeable.**

