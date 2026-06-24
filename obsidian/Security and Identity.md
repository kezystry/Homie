---
tags: [homie, concept, decision]
---

# Security and Identity

Recognition is scoped deliberately, and identity work **never reaches outward**.

| Level | What | Where |
|------|------|-------|
| 1 | Presence (no identity) | radar/thermal, on-device |
| 2 | Known faces (enrolled household) | recognized locally; only a *label* leaves |
| 3 | Flag unknown | an unrecognized person → Security |
| 4 | Returning unknown | short-TTL, encrypted, vector-only faceprint, on-device, auto-expiring |

**Out of scope by design:** identifying strangers from the internet (it inverts
local-first, is the architecture of a stalking tool, and breaks the GDPR household
exemption). Threats escalate via **capture → alert → your decision**, not auto-ID.

Identity gates [[Consent and Gestures|whose nod counts]] and what Security escalates.
Privacy is enforced fail-closed at the [[Mesh]] boundary: raw imagery/faceprints never
cross the wire. Keep each camera's field of view on your own property (*Ryneš*).
