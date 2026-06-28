"""The Coherence test (audit A-3) — the muzzle is closed by ENFORCEMENT, not convention.

The single-waist law (CHARTER #11): every owner-facing line passes through the one VoiceGate.
The render boundary is enforced (the cockpit forwards the governed `interface.spoken`, never raw
`interface.say`), but nothing stopped a component from publishing `interface.spoken` ITSELF and
reaching the owner ungoverned — the speech analog of the C2 actuator-authority bypass.

This static gate fails the moment any module other than the gate (`core/voice.py`) or the
allowlist that renders it (`core/cockpit_bridge.py`) so much as references the governed topic.
A tile that tried to forge a spoken line would have to name the string — and trip this.

Run: python3 -m unittest discover -s tests
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOVERNED = "interface.spoken"
# voice.py PRODUCES it (via the SPOKEN constant); cockpit_bridge.py lists it in the render
# allowlist tuple. No other module may PUBLISH it.
OWNERS = {"voice.py", "cockpit_bridge.py"}


def _publishes_topic(text: str, topic: str) -> bool:
    """A line that builds an Event with the literal topic = a publish (vs a docstring mention)."""
    needle_q1, needle_q2 = f'"{topic}"', f"'{topic}'"
    for line in text.splitlines():
        if "Event(" in line and (needle_q1 in line or needle_q2 in line):
            return True
    return False


class CoherenceTests(unittest.TestCase):
    def test_only_the_voicegate_owns_the_governed_speech_topic(self) -> None:
        offenders = []
        for base in ("core", "tiles"):
            for p in (ROOT / base).rglob("*.py"):
                if p.name in OWNERS or "__pycache__" in str(p):
                    continue
                if _publishes_topic(p.read_text(encoding="utf-8"), GOVERNED):
                    offenders.append(str(p.relative_to(ROOT)))
        self.assertEqual(
            offenders, [],
            f"only core/voice.py may PUBLISH '{GOVERNED}' (everything else emits interface.say and "
            f"is governed by the SpeechBudget — the C2 actuator-bypass, in speech); offenders: {offenders}")


if __name__ == "__main__":
    unittest.main()
