# Homie — working notes for the agent

## Standing instructions (remember across sessions)

- **Decide in a meeting.** Make significant technical/architectural decisions via a
  brainstorm panel of agents role-played as *actual domain professionals and
  scientists* (e.g. systems engineers, ML researchers, security/privacy experts,
  embedded/hardware engineers). Have them debate the options honestly, then chair a
  synthesis. Do not settle significant decisions solo. Trivial mechanical choices
  don't need a panel.
- **Keep the engineering discipline:** Python 3.11+, standard library only where
  feasible; ship tested code (stdlib `unittest`); keep the suite green.
- **Git:** develop, commit, and push on `claude/homie-overview-bo4l8v`. No PRs unless
  asked.

## Where things are

- **Concept & roadmap:** `OVERVIEW.md`, `DESIGN.md`; the hardware build plan + the
  decided always-on topology + the question bank live in `PLAN.md`.
- **Engineering:** `INTERNALS.md` (decisions), `PROTOCOL.md` (tile wire protocol),
  `SECURITY.md` (privacy/identity), `ARCHITECTURE.md`, `os/` (dual-boot NixOS + INSTALL).
- **Code:** `core/` (`bus`, `remember`, `tile` runtime + channels, `mesh`),
  `tiles/` (`personal`, `security`), `tests/` (44 passing), `scripts/run.py` (daemon),
  `scripts/spine_demo.py`.

## Decided architecture (see PLAN.md)

Tiered always-on: **Pi** = 24/7 lightweight learning floor + perception; **mini-PC** =
wired Home Assistant pillar; **RTX 3060 desktop** = Homie-OS-only (Proton) on-demand
heavy-LLM cortex. Continuous learning is lightweight (lives on the Pi); heavy
reasoning/fine-tuning is episodic (desktop, gated to novelty).
