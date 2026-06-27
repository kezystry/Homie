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

- **Docs live in `docs/`.** `README.md` (root) is the landing page; `CLAUDE.md`
  (root, this file) is auto-loaded agent context.
- **Concept & roadmap:** `docs/OVERVIEW.md`, `docs/DESIGN.md`, `docs/ROADMAP.md`; the
  hardware build plan + the decided always-on topology + the question bank live in
  `docs/PLAN.md`; bring-up order in `docs/BRINGUP.md`; audit backlog in `docs/BACKLOG.md`.
- **Active execution:** `docs/MASTERPLAN.md` is the crafted plan (what & why, milestones
  M0–M11); `docs/PROGRESS.md` is the living status board (how it's going — keep it updated
  in the same commit as each milestone).
- **Engineering:** `docs/INTERNALS.md` (decisions), `docs/PROTOCOL.md` (tile wire
  protocol), `docs/SECURITY.md` (privacy/identity), `docs/ARCHITECTURE.md`, `os/`
  (dual-boot NixOS + `INSTALL.md`).
- **Code:** `core/` (`bus`, `remember`, `tile` runtime + channels, `mesh`, `act`,
  `reason` (cortex: novelty-gated LLM decide loop), `reconcile`, `consent`,
  `canonical`, `ritual` (nightly consolidation)), `tiles/` (`personal`, `security`,
  `lighting`), `tests/` (295 passing), `scripts/run.py` (daemon), `scripts/spine_demo.py`.
- **Importable notes:** `obsidian/` is a cross-linked Obsidian vault mirroring the docs.

## Decided architecture (see docs/PLAN.md)

Tiered always-on: **Pi** = 24/7 lightweight learning floor + perception; **mini-PC** =
wired Home Assistant pillar; **RTX 3060 desktop** = Homie-OS-only (Proton) on-demand
heavy-LLM cortex. Continuous learning is lightweight (lives on the Pi); heavy
reasoning/fine-tuning is episodic (desktop, gated to novelty).
