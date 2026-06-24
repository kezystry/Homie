# Architecture

Homie is built from seven independent pillars that compose into a single
intelligence. Each pillar can run and be reasoned about on its own, but they
share a common analytical core: **Behavioral Analysis** models the household's
pattern of life and feeds the others — Self-Learning refines its routines from
it, and Security & Threat Escalation uses it to tell normal from anomalous.
**Home Assistant Control** is the actuation layer through which any pillar
effects change in the physical home.

## Compute split

Homie runs across two nodes, each matched to the kind of work it does.

### Perception node

- **Hardware** — Raspberry Pi with a Hailo accelerator.
- **Role** — all vision and sensor inference at the edge: Frigate, object
  detection, and processing of the thermal and radar streams.
- **Note** — the Hailo-8 and 8L are vision-only accelerators; only the 10H is
  capable of running LLMs. Perception inference therefore stays here, and
  language reasoning is delegated to the reasoning node.

### Reasoning node

- **Hardware** — desktop with an Intel i5-12400F, an RTX 3060 (12 GB), and
  32 GB of DDR4.
- **Role** — all LLM reasoning. Mixture-of-experts models (for example,
  Qwen3-30B-A3B) are used for hybrid CPU/GPU inference, keeping active
  parameter counts low enough to run responsively on this hardware.

### Rationale

Heavy perception stays in the sensor head, close to the sensors; heavy
reasoning stays on the machine with the GPU. This keeps latency-sensitive
inference local to the edge and concentrates memory- and compute-hungry
language work where the hardware for it lives.

## The "Schauender Kopf" (the watching head)

The sensor head is a ceiling-mounted unit disguised as a smoke detector, fed by
a single PoE cable that carries both power and data. Keeping it to one cable is
what lets it pass as an ordinary smoke detector.

| Subsystem | Component | Notes |
|-----------|-----------|-------|
| Power     | PoE+ splitter | 5 V / 5 A output |
| Sensing   | Thermal camera | Presence and heat-signature sensing |
| Sensing   | mmWave radar | Motion and presence without a camera |
| Sensing   | Camera Module 3 Wide | Wide-angle vision when imagery is needed |
| Inference | Hailo accelerator | Edge vision inference |
| Motion    | Feetech STS3215 smart servo | Pan actuation |

### Pan and cabling

The head pans on a single Feetech STS3215 smart servo, giving roughly 200° of
travel. Rather than a slip ring, the design uses a cable service loop that
flexes through the pan range — genuine Gigabit slip rings are prohibitively
expensive, so a service loop achieves continuous data and power across the
motion range at a fraction of the cost, at the price of not allowing
full continuous rotation.

## Pillar interactions

- **Behavioral Analysis** is the shared backbone: it produces the pattern-of-
  life model the other pillars consume.
- **Self-Learning** consumes that model to refine its understanding of the
  household's routines over time.
- **Security & Threat Escalation** compares live perception against the model to
  flag anomalies and escalate alerts in graduated steps.
- **Home Assistant Control** is the common actuation layer: when any pillar
  decides to change the environment, it acts through Home Assistant.
- **Personal Assistant**, **Werkstatt**, and **Kitchen Assistant** are
  domain-specific pillars that draw on the same perception and reasoning
  infrastructure for their respective tasks.
