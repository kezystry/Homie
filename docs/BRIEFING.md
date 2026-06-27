# Homie — briefing for a fresh reviewer

*A portable, self-contained hand-off. Paste this into any other Claude (or hand it to a
person) so they start sharp instead of confused. Last updated 2026-06-27.*

---

## What Homie is (the honest version)

Homie is a **privacy-first, self-hosted home AI** built as an "organism, not a program":
a minimal event-driven core plus a colony of self-healing capability plugins called
**tiles**, over a `Perceive → Remember → Reason → Act → Interface` spine. It learns by
**friction** — when a human reverses or remarks on what it did, the responsible tile
adjusts. Everything is **Python 3.11, standard library only**, with a green test suite
(**225 tests** as of this writing).

**Honest status (read this twice):** the *components* are individually built and tested
and the spine is genuinely strong engineering. But the full alive loop has **only ever
run in a demo script (`scripts/spine_demo.py`) with a `FakeHome`** — never in the
production daemon (`scripts/run.py`) against the real bus. Perception and voice I/O are
stubs. Homie cannot yet turn on a light when you walk in the door. See
`docs/audits/2026-06-27-review-board.md` for the full external audit; the rest of this
briefing summarizes it.

## The decided architecture

**Tiered always-on topology** (decided; see `docs/PLAN.md`):
- **Raspberry Pi** — 24/7 lightweight learning floor + perception (stdlib only, no LLM).
- **mini-PC** — wired Home Assistant pillar (the actuator bridge).
- **RTX 3060 desktop** — Homie-OS, on-demand heavy-LLM cortex, gated to *novelty*.

Continuous learning is lightweight (a decayed event-frequency histogram on the Pi);
heavy reasoning is episodic (the desktop, woken only on surprise). The split is one env
var: no `HOMIE_LLM_URL` → the LLM client is never even imported.

**Privacy floor (standing rules):** raw imagery/faceprints never cross the mesh;
training data stays encrypted, on-node, never meshed; `never_touch` entities get no
act-map entry. *(Caveat: the audit found the current `PrivacyGuard` is a heuristic, not
the "impossible by construction" guarantee the docs claim — see risk #6.)*

## Where the code lives

- `core/` — `bus`, `tile` (+ runtime/channels), `remember`, `reconcile`, `reason`
  (novelty-gated LLM decide loop), `act`, `consent`, `canonical`, `mesh`, `ritual`
  (nightly consolidation), `perceive`/`interface` (**stubs**), `cockpit_bridge`.
- `tiles/` — `personal`, `security`, `lighting`, `_template`.
- `cockpit/` — the Layer 2 curses control plane (chat + status + launcher + live cam).
- `os/boot/` — NixOS flake (`configuration.nix`, `nvidia-cuda.nix`, `apps.nix`,
  `ssh.nix`, `steam.nix`).
- `scripts/` — `run.py` (production daemon), `spine_demo.py` (the *only* place the loop
  runs end-to-end), `stage{0,2,4}.sh` (guided bring-up).
- `docs/` — concept/roadmap (`OVERVIEW`, `DESIGN`, `ROADMAP`, `PLAN`), engineering
  (`INTERNALS`, `PROTOCOL`, `SECURITY`, `ARCHITECTURE`), bring-up (`STAGES`, `BRINGUP`),
  backlog (`BACKLOG`), and **audits/** (the external review board memos).
- `CLAUDE.md` — auto-loaded agent context + standing instructions (decide significant
  things via a role-played domain-expert panel; stdlib discipline; branch
  `claude/homie-overview-bo4l8v`; no PRs unless asked).

## Physical bring-up status (the RTX 3060 desktop)

Box: IP `192.168.178.22`, user `homie`, managed over SSH from an iPhone. NixOS,
single-disk LUKS. Three distinct passwords (BIOS / LUKS / sudo).

- **Stage 0 ✅** brain alive + SSH/sudo + flakes & git permanent.
- **Stage 1 ✅** Layer 1 brain running as `homie.service`.
- **Stage 2 ✅ movies + sound.** Stremio fullscreen in a **minimal Xorg** session
  (not gamescope/Wayland) on **NVIDIA driver 550 (production, open module)**. HDMI audio
  via PipeWire works out of the box (no manual `wpctl` sink-picking needed). Command:
  `homie-watch` (run as `homie`, not root). Quit Stremio / `Alt+F4` / `pkill stremio`
  returns to console.
- **Stage 3 ⏭️ CUDA + local LLM cortex** — next on the owner's priority order. The CUDA
  toolkit is the one flaky download (not on cache.nixos.org); needs a resume-capable
  fetch.
- **Stage 4 ⏭️ Steam + Proton.** Security floor: install games **only via Steam/Proton,
  never cracked repacks** (top infostealer vector).
- **Stage 5 ✅ shipped** the cockpit (`homie`).

**Hard-won OS facts (don't re-learn these):** driver **565 = no HDMI signal** on this
3060 (both kernel modules) — stay on 550. Wayland/gamescope flickers on 550; **plain X
is rock-solid** — so movies use X. The seat group is **`seat`** not `seatd`.
`/etc/nixos` is a git tree → flakes only see **tracked** files (stage scripts `git add`
before rebuild). `lib.mkForce` needed to flip `services.xserver.enable` back on.

## The audit's verdict (2026-06-27 review board)

> **Homie is an exceptionally well-engineered torso with no senses, no hands, and no
> voice, that has never been assembled and run as a single living system.**

**The one thing to do:** collapse `run.py` + `spine_demo.py` into one `build_daemon()`,
wire a `HOMIE_FAKE_PERCEPTION=1` synthetic-day source into the *real* daemon, and write
the single end-to-end test that walks a synthetic resident through the door and asserts
a light turned on *and* a reversal was learned — on the production graph.

**Two findings worth flagging to any reviewer:**
1. `ctx.emit` bypasses the actuator permission gate — a tile can drive any mapped
   actuator at `priority: safety` (`tile.py:220`, `act.py:162`).
2. Drop-oldest backpressure can silently shed a SECURITY/SAFETY event under load
   (`bus.py:254`).

Full memo with all 10 ranked risks, the dream-vs-build gap, 8 brainstorm ideas, and a
2-week punch list: **`docs/audits/2026-06-27-review-board.md`**.

## Open decisions (good fodder for a second opinion)

1. **Why three nodes?** The audit's deepest challenge: the Pi's "learning" is a
   histogram that runs anywhere; the cortex wakes too often for the on-demand premise. A
   single mini-PC-plus-GPU might eliminate the whole mesh/partition problem class.
2. **Stage 3 CUDA fetch strategy** (aria2c vs curl `-C -` loop vs mirror) — decide via
   panel per `CLAUDE.md`.
3. **Which 8B model build** (Llama-3.1-8B-abliterated Q5_K_M is the working default).
4. **QLoRA vs retrieval** for "learning" — the audit argues the friction dataset is too
   noisy/sparse for fine-tuning; ship a retrieval "Dream Journal" instead.

## How to engage

- Read `docs/audits/2026-06-27-review-board.md` first, then `docs/OVERVIEW.md` and
  `docs/PLAN.md`, then the spine (`core/bus.py`, `core/tile.py`, `core/remember.py`).
- Run the suite: `python3 -m unittest discover -s tests` (should be green).
- Significant technical/architectural calls go through a **role-played domain-expert
  panel**, then a chaired synthesis (the project's standing rule). Trivial mechanical
  choices don't.
