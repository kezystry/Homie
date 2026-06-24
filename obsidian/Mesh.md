---
tags: [homie, component, partial]
---

# Mesh

`core/mesh.py` — node-transparent bridging across the encrypted device colony, so a
tile sees a peer's `presence.arrived` as if it were local.

- **Default-deny** — only allowlisted topics cross the wire.
- **Privacy, fail-closed** — a `PrivacyGuard` blocks raw imagery / faceprints
  (anything with `raw/image/frame/vector/faceprint/crop`), even if allowlisted.
- **No loops** — `(origin, seq)` dedup + origin-marking.

The bridging logic is built and tested behind a `Link` interface (in-memory link in
tests). The real **transport is the gap**: app-layer **Noise-IK** (vetted lib, never
hand-rolled) — one Curve25519 key per cell, a gossiped signed roster, mDNS for LAN
discovery. See [[Roadmap]] and [[Decisions log]] (deps).
