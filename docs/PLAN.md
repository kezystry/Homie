# Build Plan — Homie on your hardware

The actionable plan for turning the tested spine into the running Machine, grounded
in your kit: a **USB camera**, a **Pi + Hailo** perception node, the **RTX 3060 /
i5-12400F / 32 GB desktop** (dual-booting Windows + Homie OS), **IKEA Trådfri bulbs
+ a Dirigera hub** via Home Assistant, and a **local abliterated LLM** you can
fine-tune. Concept lives in [`OVERVIEW.md`](OVERVIEW.md); this is the how.

Read §1 first — it reshapes everything. The big question bank is §9; answer what you
can and we narrow the plan.

---

## 1. The one decision that shapes everything: always-on

A dual-boot PC runs **one OS at a time**. The moment you boot Windows to game, the
Homie brain (bus, Remember, Supervisor, LLM) is not crashed — it's *absent*. Presence
stops, Security can't escalate, automations die. A "home intelligence" that's offline
every evening isn't ambient.

**The fix all five analyses converged on: stop making one PC be both an always-on
brain and a part-time gaming rig.** Split the roles:

- **Always-on anchor** (the brainstem): a small 24/7 box runs **Home Assistant + a
  lightweight Homie core** (bus, Remember, Security, simple automations). The Pi can
  do this initially; a cheap fanless mini-PC is the clean version.
- **On-demand heavy worker** (the cortex): the **RTX 3060 desktop** joins the mesh
  *when booted into Homie OS* and serves the LLM. The big model is **gated to wake
  only when something is novel** (already an open design goal), so heavy reasoning
  being part-time is a feature, not a gap — the home stays functional on the anchor
  and is merely *enriched* when the GPU is up.
- **Connect them as encrypted mesh peers, never via a shared disk partition** — the
  mesh (heartbeat, last-will, snapshot-reconnect) is built for nodes that come and go.

If you genuinely want reasoning available *inside* Windows too, the honest option is
running the daemon under WSL2 as **its own mesh node** (own identity), not a clone and
not a file-share — accepting that it lives on an un-hardened OS. Recommended only if §9
Q5 says you need it.

---

## 2. Hardware — decisive answers

| Question | Answer | Why |
|----------|--------|-----|
| **Hailo 8 vs 8L vs 10H?** | **Hailo-8 (26 TOPS)** | The Pi does *vision only* (Frigate detection + face recognition). The 10H's value is edge LLMs — redundant with your 3060. The 8 (vs 8L) gives headroom for face recognition + a future 2nd camera/thermal/radar. |
| **Pi 4 or 5? 4 GB or 8 GB?** | **Pi 5, 8 GB** | Hailo attaches over PCIe via the AI HAT+ — Pi 5 only. 4 GB is tight once you co-locate Frigate + decode + adapter + mesh; 8 GB is the sweet spot, 16 GB overkill for vision. |
| **Camera on Pi or desktop?** | **On the Pi** | Keeps raw frames at the edge (the privacy guarantee) and the desktop is off/in-Windows half the time. |
| **Always-on box?** | **Yes — Pi now, mini-PC ideal** | See §1. Don't co-locate HA on the perception Pi long-term (pollutes the privacy-critical edge node); a dedicated HAOS box is cleaner. |

**Perception BOM (~€230–290):** Pi 5 8 GB (~€85) · Raspberry Pi AI HAT+ (Hailo-8, 26
TOPS, ~€110–130) · active cooler (mandatory) · official 27 W USB-C PSU · good A2
microSD (NVMe competes with the Hailo for the single PCIe lane — start on SD).

**Camera:** any clean UVC webcam that exposes **MJPEG/H.264** (not raw YUYV) so the Pi
isn't burning CPU on compression. 1080p is plenty; aim it **on your own property only**
(the GDPR/Ryneš line). Plug into the Pi.

**Power/network:** wired Ethernet for both desktop and (ideally) Pi; USB power for the
Pi on a shelf now, PoE+ later when it becomes the ceiling sensor head.

**Zigbee/Thread radio (to buy):** **SONOFF Zigbee/Thread PoE Dongle Max** (EFR32MG24 +
ESP32, dual antenna). Network-attached (Ethernet/PoE/Wi-Fi/USB) so it mounts centrally,
away from the PC's USB-3 interference, and gives Home Assistant its own Zigbee coordinator
(ZHA / Zigbee2MQTT) — Zigbee *and* Thread/Matter for the future. Run it alongside the
Dirigera hub (IKEA bulbs) or migrate devices onto it for fully HA-native control.
→ https://www.amazon.de/SONOFF-unterst%C3%BCtzt-USB-Verbindungen-Zigbee-Gateway-Zigbee-Stick/dp/B0FMJH4DPN

---

## 3. Topology — where everything runs

```
                         Home LAN (wired switch + Wi-Fi AP, mDNS allowed)
  ┌───────────────────────┬───────────────────────┬────────────────────┬───────────────┐
  │                       │                       │                    │               │
 Pi 5 + Hailo-8       Always-on box           Desktop (dual-boot)   Dirigera hub   (laptop/phone,
 PERCEPTION          ANCHOR / HA              REASONING (on-demand) IKEA Zigbee     later peers)
 - Frigate + camera  - Home Assistant 24/7    - Homie OS (NixOS)    - Trådfri bulbs
 - identity ladder   - Mosquitto (MQTT seam)  - LLM on RTX 3060
 - perception adapter- light Homie core       - joins mesh when up
 - Noise peer        - canonical durability log
        └──────────── app-layer Noise-IK encrypted mesh; mDNS discovery; signed roster ──────────┘
```

- **Perception (Pi):** Frigate + Hailo + camera → normalized events only. Raw frames
  never leave. Noise peer + event producer, **not a tile**.
- **Anchor box:** Home Assistant + Mosquitto + the always-on core (Remember, Security,
  simple tiles). Holds the canonical pattern of life.
- **Reasoning (desktop):** the LLM + heavy tiles, live only in Homie OS; gated to novelty.
- **HA ↔ Homie:** MQTT, the one sanctioned seam. Homie is an MQTT client; HA owns the
  IKEA token and the broker.

---

## 4. Build phases

Each phase ships something that works; later phases need earlier ones.

- **Phase 0 — Buy & prep.** Pi 5 8 GB + AI HAT+ (Hailo-8) + cooler + PSU. Migrate the
  Trådfri bulbs onto the Dirigera hub (factory-reset + re-pair — they don't import).
  DHCP-reserve the hub's IP. Decide the always-on box (Pi vs mini-PC).
- **Phase 1 — Validate the OS in a VM.** `nixos-rebuild build-vm` the config; confirm
  it boots, prompts for LUKS, autologins, and `homie.service` starts (the repo must be
  at `/opt/homie` in the VM, or the service ImportErrors). **Do not touch the real disk
  until this is green.** Add the missing NVIDIA/CUDA config (see §7).
- **Phase 2 — Home Assistant + first light.** HAOS on the anchor box; integrate Dirigera
  (community local-API `dirigera_platform`, Matter as fallback); expose the bulbs.
  Stand up Mosquitto. Build `core/act.py` as the MQTT gateway + an explicit
  `deploy/act_map.toml`. Manually publish an `actuator.requested` → watch a real bulb
  turn on. **First visible win.**
- **Phase 3 — Perception v1.** Frigate on the Pi with the Hailo detector + the USB cam;
  zones + privacy masks; a Python perception adapter that turns Frigate object events
  into `presence.*`/`motion.*`/`occupancy.*` and publishes them. Single-node first
  (everything loopback), then split.
- **Phase 4 — The mesh transport.** Implement `NoiseLink` (the missing `Link`) +
  mDNS discovery + signed roster, so the Pi and the anchor/desktop actually talk. Wire
  it into `run.py`. Now presence on the Pi reaches Security on the anchor.
- **Phase 5 — Close the friction loop.** The `StateReconciler`: HA state changes Homie
  didn't cause → `note_reversal`/`note_manual` (with echo-suppression to avoid a feedback
  loop). Ship a `lighting` tile: presence-driven, pattern-gated room lighting that learns
  from your reversals. This exercises the *entire* path end to end on real hardware.
- **Phase 6 — Reason (LLM).** Serve the abliterated model on the 3060 via llama.cpp/Ollama
  (OpenAI-compatible, loopback). Implement `Reason.decide` + a gate (wake only on novel
  events) + tool-calling from tile `functions`. Reason proposes; the bus arbitrates.
- **Phase 7 — Interface (voice) + fine-tuning.** Voice in/out; spoken remarks → `note_remark`.
  Begin the QLoRA fine-tune loop, turning friction (reversals/remarks) into preference data.
- **Phase 8 — Hardening & ops.** Log rotation/compaction, encrypted backup of the pattern
  of life, package `/opt/homie` as a Nix derivation for atomic updates, LUKS-unlock
  strategy, sensor head (thermal/radar, PoE, ceiling mount).

---

## 5. Layer plans (condensed)

### Perception (Pi)
USB cam → go2rtc restream → **Frigate** (Hailo detector, YOLO `.hef`) → a **Python
adapter** that subscribes to Frigate's MQTT/events (never pixels), runs a per-zone
presence FSM (debounce), and publishes normalized events. Topics must be exactly what
the spine expects (`presence.arrived/updated/departed`, `presence.known/unknown`,
`motion.detected`, `occupancy.changed`) with a **`zone`** in every payload. Identity
ladder, all on-device: person detect (L1) → Frigate face recognition of enrolled
household (L2, emits a *label* "alice") → flag-unknown (L3) → returning-unknown
(L4: encrypted vector-only gallery, TTL auto-expiry, emits only `recurring`+opaque
token). **Never emitted:** frames, crops, bboxes, embeddings — enforced by a local
`assert_emittable` mirroring the mesh `PrivacyGuard`. Python+Frigate for v1; port the
hot path to Rust later (same wire events). Field-of-view masking over any window.

### Reason (desktop, RTX 3060 12 GB)
**llama.cpp/Ollama**, OpenAI-compatible on loopback. **8B-class abliterated model at
Q5_K_M** as daily driver (fully on-GPU, fast, room for context); 14B Q4_K_M only if
quality demands and latency allows. **Two-tier gate:** a cheap Python predicate over
`Expectation` handles the normal 95% (do nothing / hand to the tile); the LLM wakes
only on `novel`/rare divergence (coalesced per zone) — cheap by default, GPU only on
novelty. Reason **reads** Remember + the live event, **proposes** via tile tool-calls
or `interface.say`, and **drives nothing directly** — the bus priority arbitration
(`SAFETY > SECURITY > AUTOMATION > CONVENIENCE > AMBIENT`) and per-tile actuator
permissions are the safety floor. *The abliterated/uncensored model is a non-issue for
home safety precisely because safety is structural, not behavioral — never give Reason
a path around arbitration.* Snapshot `Expectation` at event time (evaluate-then-learn).
Fine-tune via **QLoRA on the 8B** (adapter-only, short context, overnight); friction
(remark > reversal > repeat) is already shaped like DPO preference pairs. Keep base +
prior adapter for one-line rollback.

### Act (Home Assistant — IKEA Dirigera + Trådfri)
HA on the **always-on box** (not the dual-boot desktop). Integrate Dirigera via the
community **local-API** integration (real-time WebSocket, lower latency; Matter bridge
as fallback). `core/act.py` = the single gateway: subscribe `actuator.requested`,
arbitrate via `Bus.arbitrate`, map `actuator → entity_id` from an explicit
`deploy/act_map.toml` (which is also the allowlist + the never-touch guard), drive HA
over **MQTT only** (`mqtt_statestream` for state in, a small command convention out),
confirm via state-change, emit `actuator.done`/`actuator.failed`. HA holds the IKEA
token + Mosquitto; Homie is a pure MQTT client.

### The friction producer (the missing piece)
A **`StateReconciler`** beside Act: every HA state change Homie did **not** cause is a
human action. Echo-suppress Homie's own commands (tag with `action_id`, short
reconciliation window), then: a change that reverses a recent Homie act → `note_reversal`;
a human action on an actuator Homie didn't touch → `note_manual` (after threshold). The
Supervisor already consumes these — **zero Supervisor changes**, this is the producer
it was waiting for. This closes self-learning with real hardware.

### Mesh transport (the real gap)
`core/mesh.py` (bridge, policy, privacy guard, loop suppression) is done and tested
against an in-memory `Link`; **nothing implements `Link` over a socket.** Build
`deploy/mesh/`: `identity.py` (one X25519 static key = node id, stored in LUKS),
`noiselink.py` (**Noise-IK** via a vetted lib like `dissononce`/`noiseprotocol` — never
hand-rolled — framed over TCP, unprivileged, no kernel/WireGuard), `discovery.py`
(`zeroconf` mDNS, endpoints only), `roster.py` (signed gossiped peer roster = trust,
no CA, TOFU-with-verification). `NoiseLink` implements `send`/`on_receive` → drops in
behind `MeshBridge` with **zero bridge changes**; the only new wiring is in `run.py`.

### OS / dual-boot / ops / security
Validate via `build-vm` before the real disk. Windows gotchas in order of danger:
**BitLocker** (export the recovery key first — #1 lockout cause), **Fast Startup/
hibernation** (disable, true shutdown), **Secure Boot** (off, before install while you
hold the BitLocker key), NTFS shrink from Windows' own tool, ESP size. Take a **block
image backup** first. Known gaps to close: the config installs **no GPU driver** (the
reasoning node *is* the 3060 — add NVIDIA/CUDA); **LUKS unlock is interactive** (fights
always-on — choose passphrase-at-boot vs TPM2 vs initrd-SSH remote unlock); **`/opt/homie`
is a plain copy outside Nix's rollback** (package it as a derivation); the **durability
log is append-only and replayed wholesale on boot** (add rotation/compaction); back up
`/var/lib/homie` **encrypted** off the LUKS volume.

---

## 6. Code gaps to close (concrete)

1. **Tool-call schemas** — manifests list function *names* only; real tool-calling needs
   param schemas. Extend `tile.toml` `[provides]` with per-function description+params (or
   introspect handler type hints in the Supervisor). Add `Supervisor.tool_catalog()`.
2. **`StateReconciler`** — the friction producer (HA state → `note_*`), with echo-suppression.
3. **`NoiseLink` + `deploy/mesh/`** — implement the `Link` transport; wire into `run.py`.
4. **NVIDIA/CUDA in `configuration.nix`** — the reasoning node can't use its GPU otherwise.
5. **Durability log rotation/compaction** — snapshot derived state + truncate the raw log.
6. **Package `/opt/homie` as a Nix derivation** — atomic app updates + rollback.
7. **`Reason.decide` + gate + runner** in `core/reason.py`; wire `Reason` beside `remember`.
8. **`core/act.py` + `deploy/act_map.toml`**; **perception adapter**; **`lighting` tile**.

---

## 7. The abliterated model — the honest take

It's your own local model, on your own hardware, for your own home — treated neutrally.
The only real question is "can a refusal-free model take *unsafe physical actions*?", and
the architecture already answers it: **safety is structural.** Reason owns no actuators,
drives nothing directly, and every physical effect is mediated by a tile that declared
that actuator and arbitrated by the bus, where a SAFETY-tier rule always wins. Keep
locks/garage/anything dangerous behind an explicit ask or a SECURITY/SAFETY-tier tile,
never a CONVENIENCE auto-action. Validate tool calls structurally (name+args) before
executing. Net: keep arbitration + per-tile permissions as the floor and never give
Reason a bypass, and the abliteration is a non-issue for the home.

---

## 8. The dumb-when-gaming reality (say it plainly)

With the desktop as the only brain, the home is reason-less whenever you're in Windows or
off. The Pi-as-anchor (§1) keeps presence, security alerts, and simple automations alive
24/7; only *heavy* LLM judgment waits for the desktop — and the novelty-gate makes that
acceptable. Whatever you choose, the desktop dropping must emit a `node.down` last-will so
tiles degrade to safe defaults instead of hanging. Decide §9 Q1–Q6 and this resolves.

---

## 9. The question bank

Answer by number (e.g. "Q3: living room + hallway; Q12: never touch the office heater").
Grouped; the ⭐ ones gate the most.

### A. Always-on & topology
- ⭐ Q1. What fraction of the day is the desktop in **Windows vs Homie OS vs off**?
- ⭐ Q2. When you're in Windows, what **must still work** — security alerts? presence-lighting? Or is "dumb while gaming" acceptable?
- ⭐ Q3. Will you run the **always-on anchor on the Pi** for now, or buy/repurpose a **mini-PC** for HA + the light core?
- Q4. Is the Pi truly 24/7, on a UPS? Independent of the desktop's power?
- ⭐ Q5. Do you want reasoning available **inside Windows** (WSL2 mesh node), or is reason-less-during-Windows fine?
- Q6. If WSL2: GPU passthrough (CUDA) needed there, or CPU-only?
- Q7. When you said the two OSes should "connect," do you mean (i) brain available in both boots, (ii) shared state across reboots, or (iii) just file exchange?

### B. Hardware / camera
- Q8. Confirm the LLM stays **only** on the 3060 (no edge-LLM ambition on the Pi)?
- Q9. How many cameras within a year — one webcam, or the full thermal+radar+camera head?
- Q10. Committing to the ceiling **PoE sensor head**, or shelf USB webcam for the foreseeable future?
- Q11. Webcam model + supported formats (MJPEG/H.264 vs raw YUYV)?
- Q12. Where does the camera sit, and does its field of view stay **entirely on your property**? Any window/street in view (to mask)?
- Q13. microSD to start, or NVMe on the Pi (competes with the Hailo for PCIe)?

### C. Network
- Q14. Can the desktop and Pi both be **wired** to one switch, or is the Pi Wi-Fi-only?
- Q15. Does your router/AP pass **mDNS/multicast** (needed for peer discovery), or is there client isolation/VLAN?
- Q16. Put Homie devices on a separate **IoT VLAN**?

### D. Home Assistant / IKEA
- ⭐ Q17. Are the old Trådfri bulbs already **migrated to the Dirigera**, or still to do? (Blocks everything light-related.)
- Q18. Exactly which rooms have bulbs, how many each, and are any **color/tunable** or all warm-white?
- Q19. Can you put the Dirigera hub on a **fixed IP** (DHCP reservation)?
- Q20. Which rooms light **automatically** on presence vs only **on request**? (Bedroom auto-on at 3am is usually unwelcome.)
- Q21. After-dark only? Auto-**off** on leaving — after how long? Whole-house "all off when empty"?
- ⭐ Q22. **Which entities must Homie NEVER control** (heating, locks, anything safety-adjacent)? These get no mapping.
- Q23. Entities Homie may **read** (for learning) but never **write**?
- Q24. Any HA-native automations you'll keep (sunset porch light, vacation mode)? Keep them HA-owned/unmapped to avoid two brains fighting one bulb.
- Q25. Do you use **scenes**? Should Homie invoke a scene as one actuator?
- Q26. When Homie acts, **confirm by voice** or act silently (speak only on failure)?

### E. Reasoning / LLM
- ⭐ Q27. Which **abliterated model + parameter count** (7/8/14B)?
- Q28. Does that checkpoint ship a working **tool-calling chat template**?
- Q29. Ollama (fast) or `llama-server` (KV-quant, explicit offload)?
- Q30. Acceptable decision latency (sub-second ambient, ~2 s spoken)? Justifies 8B-over-14B?
- Q31. Keep the model **warm when someone's home**, unload when empty — OK?
- ⭐ Q32. Default autonomy: **act-then-let-me-reverse**, or **ask-before-acting**? (Reshapes the whole loop.)
- Q33. Which actuator classes are **never autonomous** (locks/garage) and always ask first?
- Q34. Persona/voice — terse/butler/warm/dry? How chatty by default?
- Q35. Multi-resident: one shared persona, or per-person? (Bears on friction attribution.)

### F. Fine-tuning & training data
- Q36. Cadence: overnight/weekly/manual-only? SFT only, or SFT + DPO on reversal/remark pairs?
- Q37. Promote each new adapter by **hand-approval** against a held-out eval, or auto-promote if eval passes?
- Q38. How much hand-authored **seed data** will you write (persona + ask/act boundary + format)? 50? 200?
- Q39. Confirm training data (your household's behavior) stays **encrypted, on-node, never meshed/backed-up off-box**? Any rooms/times/guests to exclude?

### G. Perception behavior
- ⭐ Q40. One camera for v1 — which single space matters most (front door? living area? office)?
- Q41. Zone names to carve the view into (`front-door`, `kitchen`, …)? Map 1:1 to lit rooms?
- Q42. Who to **enroll** as known faces (names → labels)? Consent to on-device reference images?
- Q43. Anyone detected as "person" but **deliberately not face-recognized** (e.g. kids)?
- Q44. Want **returning-unknown** (L4) in v1, or is flag-unknown (L3) enough? If L4, what **TTL** (hours/day/week)?
- Q45. How aggressive should **flag-unknown** be — every unrecognized face, or only when pattern-of-life says it's unusual?
- Q46. **Pets**? Emit pet events or suppress? Known false-positive sources (TV faces, mirrors, windows)?
- Q47. **Detect-only (no recording)** for v1, or a short encrypted buffer for review? On an alert, does "capture" mean a saved still or just the event?
- Q48. Camera always-on, or gated/scheduled (off certain hours, off when a resident is home)?

### H. OS / dual-boot / backup
- ⭐ Q49. Is Windows **BitLocker**-encrypted? Do you have the recovery key saved off-machine?
- Q50. UEFI confirmed? Current ESP size? How much free space for Homie (60–100 GB + room for LLM weights)?
- Q51. Want a small **exFAT scratch partition** for non-sensitive Windows↔Homie file exchange, or fully separate?
- ⭐ Q52. LUKS unlock: **passphrase at every boot** (max security, fights always-on), **TPM2 auto-unlock**, or **initrd-SSH remote unlock**?
- Q53. Backup target for `/var/lib/homie` (the pattern of life): Pi / NAS / off-site — and keep it encrypted off the LUKS volume?
- Q54. OK to **compact/rotate** the durability log, or retain full raw history forever?
- Q55. Package `/opt/homie` into Nix for atomic update+rollback (recommended), or keep the manual copy for now?
- Q56. Enable **SSH** on the desktop for maintenance (key-only), or keep it off?

### I. Security / threat model
- ⭐ Q57. Who else lives there / has physical access? Who gets enrolled faces?
- Q58. What's the actual adversary — opportunistic theft, a curious housemate, a targeted attacker? (Drives LUKS/Secure-Boot choices.)
- Q59. Confirm you accept that with **Secure Boot off + a shared disk**, a compromised Windows has no enforced boot-integrity barrier to the Homie ESP/GRUB?
- Q60. Do you need **remote access** from outside the home (status/unlock/LLM)? Over what (Tailscale/WireGuard)? (It contradicts local-first — deliberate call.)
- Q61. Enrollment UX for new mesh nodes: verify each key fingerprint by hand (TOFU), or want a QR pairing flow? Which devices join now vs later (Pi + desktop + anchor; laptop/phone)?

### J. Scope of the first build
- ⭐ Q62. v1 **single-node** (everything on the Pi to start, mesh is loopback) or **multi-node now** (Pi + anchor + desktop)?
- Q63. What's the very first thing you want to *see work* — a light reacting to presence, a security alert, or the LLM answering a question?

---

## 10. Always-on: the options in depth

The constraint, restated: "always-on" needs a machine that is **actually powered 24/7
and cheap/quiet to leave on**. A gaming desktop with an RTX 3060 is neither (loud, ~60–100 W
idle, and you reboot it into Windows). So the real question is *which box is the brainstem*,
and separately *where the heavy LLM lives*. Six honest options:

### Option 1 — Pi as the anchor (no new hardware) ⭐ start here
The Pi you're already buying runs 24/7. Put **Home Assistant + a lightweight Homie core**
(bus, Remember, Security, simple automations) on it alongside perception; the desktop is an
**on-demand GPU worker** that joins the mesh only in Homie OS.
- **Always-on?** Yes. **Runs the 8B LLM always?** No — the Pi can't; heavy reasoning waits
  for the desktop (gated to novelty, so the home still works).
- **Cost:** €0 extra. **Complexity:** low. **Gaming:** untouched.
- **Caveat:** co-locating HA + core on the privacy-critical perception Pi is a little
  impure and competes for its RAM/thermal budget. Fine to start; move HA off later (Option 2).

### Option 2 — Dedicated mini-PC anchor (Intel N100/N305) ⭐ clean end-state
A cheap fanless mini-PC (~€150–250, ~6–10 W idle, silent) runs **HA + the always-on core**
24/7. The Pi stays a pure perception node; the desktop stays the on-demand GPU. An N305/iGPU
box can even serve a **small always-on LLM** (1–3B) for trivial decisions, with the 3060 as
the "big brain on novelty."
- **Always-on?** Yes. **8B LLM always?** No (small model maybe; big model on the desktop).
- **Cost:** one mini-PC. **Complexity:** low. **Gaming:** untouched. **Cleanest split of roles.**

### Option 3 — Make Homie OS your *only* OS; game via Proton ⭐ if your games allow
Drop dual-boot entirely. The desktop runs **Homie OS 24/7 as your daily driver**, and you
play games on Linux via **Steam/Proton**. Now the GPU box *is* always-on and the whole
problem evaporates — heavy LLM is always available too.
- **Always-on?** Yes, including the 8B LLM. **Cost:** €0. **Complexity:** medium (Linux daily
  driver). **Gaming:** depends entirely on **your games' anti-cheat** — most single-player and
  many multiplayer titles run great on Proton; some kernel-anti-cheat games (certain
  competitive shooters) don't. **This is the most elegant fix if your library is Proton-friendly.**
- **Caveat:** leaving a 3060 desktop on 24/7 costs more power than a mini-PC; you can suspend
  it and wake-on-LAN / wake-on-event if idle power matters.

### Option 4 — Hypervisor base running both at once (Proxmox/KVM + GPU passthrough)
This is the literal "both partitions running" answer. Install a thin hypervisor (Proxmox/KVM)
as the real OS; run **Windows and Homie OS as simultaneous VMs**, passing the RTX 3060 to
whichever needs it via **VFIO**.
- **Always-on?** Yes — Homie VM runs whenever the machine is powered. **8B LLM always?** Only
  when the GPU is assigned to the Homie VM; a single GPU can't be in both VMs at once, so
  gaming (GPU → Windows) and heavy LLM (GPU → Homie) still contend — you'd hand the card back
  and forth. **Cost:** €0 hardware. **Complexity:** **high** (VFIO/IOMMU, single-GPU passthrough
  is fiddly), and it weakens Homie's clean hardened-OS story. **Gaming:** works but with VM overhead.
- **Verdict:** technically the "run both off different partitions simultaneously" option, but the
  single-GPU contention and complexity make it worse than Option 2 or 3 for most people.

### Option 5 — Homie under Windows (WSL2/Docker) as a stopgap
Run the daemon under WSL2 so the brain is up **whenever the PC is on and in Windows**, as its
own mesh node.
- **Always-on?** No — only while Windows is booted and the PC is on; dies when off or in Homie OS.
  **Security:** regression (un-hardened OS). **Use:** a bridge to keep reasoning alive during
  Windows sessions, not a real anchor. Pair with Option 1/2 for the 24/7 floor.

### Option 6 — A second, dedicated GPU box
A separate always-on Linux machine *with its own GPU* runs the full stack including the LLM 24/7.
- **Always-on?** Yes, including the LLM. **Cost:** highest (another GPU box). **Complexity:** low.
  **Gaming:** desktop stays Windows-only. Overkill unless you want full reasoning always-on and
  don't mind the spend/power.

### Decision matrix

| Option | 24/7 brain | 8B LLM always | Extra cost | Complexity | Keeps Windows gaming |
|--------|:---------:|:-------------:|:----------:|:----------:|:--------------------:|
| 1. Pi anchor | ✅ | ❌ (desktop on-demand) | €0 | Low | ✅ |
| 2. Mini-PC anchor | ✅ | ❌ (small model maybe) | €150–250 | Low | ✅ |
| 3. Homie-OS-only + Proton | ✅ | ✅ | €0 | Medium | ⚠️ if Proton-compatible |
| 4. Hypervisor + VFIO | ✅ | ⚠️ GPU contention | €0 | High | ✅ (VM) |
| 5. WSL2 in Windows | ❌ | ⚠️ when in Windows | €0 | Low | ✅ |
| 6. Second GPU box | ✅ | ✅ | High | Low | ✅ |

### Recommendation
**Start with Option 1** (Pi anchor — you're buying the Pi anyway, zero extra cost, the home is
always-on for everything except heavy LLM). **Grow into Option 2** (mini-PC anchor) when you
want HA + the core off the perception Pi. **Seriously consider Option 3** if your game library
runs on Proton — it's the most elegant: one box, always-on, big LLM included, no Windows gap at
all. Avoid Option 4 unless you specifically want one machine doing literally everything and are
comfortable with VFIO. Use Option 5 only as a Windows-session bridge on top of 1/2.

The deciding inputs are **Q1/Q2** (how often you're in Windows and what must survive it) and one
new question: **do your games run on Linux/Proton?** — because if they do, Option 3 makes the
whole always-on problem disappear.
