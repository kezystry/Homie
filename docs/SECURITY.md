# Security & Privacy

Homie is built to be safe even if found.

## Posture

- **Local-first** — data never leaves your network unless you explicitly permit
  it.
- **Encrypted** — full-disk encryption; encrypted state and peer links; no
  cloud, no accounts, no telemetry.
- **Headless** — minimal footprint, runs without a UI, nothing chatty on the
  network. Discretion through minimalism, not anti-forensics.
- **Per-tile secrets** — each tile owns its own credentials and state; a
  compromised tile cannot read another's.

## Identity model

Recognition is scoped deliberately, from least to most invasive:

1. **Presence** — a person is here; no identity (radar/thermal).
2. **Known faces** — people you have enrolled (household, regular guests),
   recognized locally.
3. **Flag unknown** — someone unrecognized is present → Security.
4. **Returning unknown** — a short-lived, encrypted, vector-only faceprint (no
   photos kept), held on-device with the camera's field of view on your own
   property, auto-expiring. It distinguishes "the same unknown returned" from "a
   new person." Never named, never leaves the device.

### Out of scope, by design

- **Identifying strangers from the internet or public data.** It inverts
  local-first, it is the architecture of a stalking tool, and it falls outside
  the GDPR household exemption. Threats escalate instead via **capture → alert →
  your decision** (and, if warranted, law enforcement with due process).
- **Tracking identified people beyond your property.**

## Why the line holds

Local recognition of consenting residents sits inside GDPR's household
exemption. Reaching outward to identify non-consenting people does not. Keeping
each camera's field of view on your own property is what keeps the exemption
intact (cf. *Ryneš*, C-212/13).
