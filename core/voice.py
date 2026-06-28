"""The Voice waist — the single point every owner-facing line passes through.

Tiles and the cortex emit `interface.say` ("here is a fact worth saying"). They do NOT
decide whether the owner actually hears it — that is this gate's job, and ONLY this gate's.
`VoiceGate` subscribes to `interface.say`, asks the `SpeechGovernor` (budget + mute +
ledger) whether to speak now, and republishes:

  * `interface.spoken` — the governed channel the cockpit/voice front-end actually renders.
    The owner hears this, never the raw `interface.say`.
  * `speech.deferred`  — over-budget or muted lines. The morning recap MAY collapse these
    into a single lossy count ("+6 minor things"); most simply die unspoken, which is the
    correct behaviour for a silent-by-default home (external audit §4.1: a thought worth
    saying tomorrow wasn't worth saying — a count is honest, a "never dropped" promise is
    not). The channel exists so the recap can show the count, NOT to guarantee resurfacing.

This is the architectural muzzle: there is exactly ONE governor on the only channel that
can nag the owner, wired unconditionally in `build_daemon`. Adding a tenth talking feature
adds a tile that emits facts; it can never grow its own ungoverned mouth, because the
cockpit only ever renders `interface.spoken`.

It also owns the everyday mute: `voice.mute` (`{seconds}`) / `voice.unmute` control events
let the owner say "quiet for an hour" in the moment. Safety/summons speech (`kind` in
`EXEMPT_KINDS`) bypasses both budget and mute — a hazard is always heard.
"""
from __future__ import annotations

import logging

from core.speech_budget import SpeechGovernor
from core.tile import Event

log = logging.getLogger("homie.voice")

SAY = "interface.say"          # in: a tile/cortex proposes a line (ungoverned)
SPOKEN = "interface.spoken"    # out: the governed line the owner actually hears
DEFERRED = "speech.deferred"   # out: held for the morning recap (never dropped)
MUTE = "voice.mute"            # in: owner "quiet for {seconds}"
UNMUTE = "voice.unmute"        # in: owner "you can talk again"

DEFAULT_MUTE_SECONDS = 3600.0  # "quiet for an hour" when no duration is given


class VoiceGate:
    """The governor on the bus. Construct in `build_daemon`, `start()` after the tiles so
    its subscription is live before they speak, `stop()` on shutdown. Holds the only
    `SpeechGovernor`; `snapshot()` exposes the ledger for the cockpit / recap."""

    def __init__(self, bus, *, governor: SpeechGovernor | None = None) -> None:
        self.bus = bus
        self.gov = governor or SpeechGovernor()
        self._subs: list = []

    async def start(self) -> None:
        self._subs = [
            self.bus.subscribe(SAY, self._on_say, owner="voice"),
            self.bus.subscribe(MUTE, self._on_mute, owner="voice"),
            self.bus.subscribe(UNMUTE, self._on_unmute, owner="voice"),
        ]

    async def stop(self) -> None:
        for sub in self._subs:
            self.bus.unsubscribe(sub)
        self._subs = []

    async def _on_say(self, event: Event) -> None:
        text = event.payload.get("text")
        kind = event.payload.get("kind", "proactive")
        decision = self.gov.decide(event.ts, kind=kind, source=event.source)
        topic = SPOKEN if decision.spoken else DEFERRED
        payload = {"text": text, "kind": kind, "outcome": decision.outcome}
        await self.bus.publish(Event(topic, event.ts, payload, source=event.source))

    async def _on_mute(self, event: Event) -> None:
        seconds = event.payload.get("seconds", DEFAULT_MUTE_SECONDS)
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = DEFAULT_MUTE_SECONDS
        self.gov.mute.mute(event.ts, seconds)
        log.info("voice: muted for %.0fs", seconds)

    async def _on_unmute(self, event: Event) -> None:
        self.gov.mute.unmute()
        log.info("voice: unmuted")

    def snapshot(self) -> dict:
        return self.gov.ledger.snapshot()
