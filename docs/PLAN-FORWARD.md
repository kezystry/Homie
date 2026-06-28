# Homie — the plan (current & clean, 2026-06-28)

*This is the single, honest, plain-language plan. Where older planning docs disagree, this one
wins. The non-negotiable rules live in [`docs/CHARTER.md`](CHARTER.md); the detailed scope filter
in [`docs/SCOPE.md`](SCOPE.md); the live status in [`docs/PROGRESS.md`](PROGRESS.md). This file
is the map you read top to bottom.*

---

## Where we are (real, verified — 459 tests green)

Homie is a private home AI on your own machines. No cloud, nothing leaves your network. It
learns your home by watching and by *friction* (silence = approval, a correction = a lesson).

**Working today:**
- The full loop (perceive → remember → reason → act → speak), one tested wiring.
- **It knows you** — an honest model of your routines + a plain "What Homie Knows" page.
- **The morning surface** — a recap of yesterday and a briefing for today (agenda, due things,
  a sensible errand order), capped so it never floods.
- **A self-pacing voice** — no fixed limit; it *learns* how chatty to be (mute it → it talks less).
- **Your real lights** — Home Assistant + DIRIGERA + every bulb, with Homie driving them (live).
- **A real yes/no** — you can now answer "are you sure?" in plain chat (just shipped).

**Not built yet (honestly):** the GPU brain/voice aren't stood up; guardian, business, camera,
and self-upgrade are deliberately deferred until the soul is lived-in.

---

## The plan, as things you'll feel (in order)

Each step is one milestone. Top to bottom is the future.

1. **It remembers you, honestly** — ✅ done. Routines as true probabilities; a page you can read.
2. **Your mornings are handled** — ✅ done. Recap + briefing, never a wall of text.
3. **It won't nag** — ✅ done. The voice learns its own volume from how you react.
4. **It controls your home** — ✅ done. Real lights, driven and learned-from.
5. **You can say yes/no** — ✅ just shipped. The confirm gate finally works.
6. **An undo button** — 🔜 **next.** Scroll back and reverse anything Homie did, in one tap, with
   a tidy list of every correction. *(This is what we build now.)*
7. **The lights act on their own** — 🔜 dusk first (a light comes on by itself), then "light the
   room when you walk in" once a motion sensor exists. It offers once, then just does it.
8. **The day fills in** — 🔜 your real calendar + weather woven into the briefing.
9. **It sees what changed overnight** — 🔜 the nightly tidy writes a short "what improved" note.
10. **The house is locked down** — 🅿️ the egress chokepoint + system hardening.
11. **The guardian wakes up** — 🅿️ intrusion deterrence, hazard sensors, emergency calling (gated).
12. **The butler arrives** — 🅿️ life-admin + KartenWerk, drafts you approve (money always asks).
13. **It takes care of itself** — 🅿️ nightly self-upgrade, owner-signed, auto-rollback.
14. **It begins to see** — 🅿️🧱 presence → mood → distress at the two entrances, gated rung by rung.

✅ done · 🔜 next few · 🅿️ deferred on purpose (built once the soul is lived-in)

---

## What we build now (step 6 — the undo button)

The next concrete work, in small safe slices:
1. ✅ **The yes/no producer** (done) — Homie can be answered.
2. **The Friction Ledger** — every action Homie takes becomes a plain, selectable row.
3. **One-key undo** — selecting a row issues the inverse action through the same safe path, and
   records the strongest "you were wrong" correction so it learns.
4. Then **step 7**: a dusk lighting automation (offer once → act), so a light comes on tonight.

After that, live with it for a few weeks and let what you actually reach for decide step 12+.

---

## The hardware track (when you want)

- **A motion/presence sensor** — the single biggest unlock (autonomy, "welcome back", room
  lighting, mood). IKEA ones pair into your DIRIGERA and appear in HA like the bulbs did.
- **The mini-PC** eventually hosts Home Assistant (so lights work while the desktop sleeps) —
  your compose folder moves over as-is.
- **The GPU brain** (local model) for real conversation; **the Pi + camera** for the vision track.

---

## What we are deliberately NOT doing now (and why)

Per the scope discipline (every ADD names a CUT): the heavy memory codec, three-node mesh,
autonomous cyber-defense, camera intent-reading, and fine-tuning are all shelved until a real
need names them. This is on purpose — it's how "everything" avoids becoming over-complex.

---

## Decisions waiting on you (no rush)

- Set your **secret name** (it's a password — only you know it).
- Buy a **motion sensor**? (unlocks the most).
- Later: emergency-call rules · self-upgrade signing-key custody · when to start **KartenWerk**.
