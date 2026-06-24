"""Interface — voice-first I/O and the friction channel.

Carries questions and answers, and turns your reactions — reversals, repeated
manual actions, spoken remarks — into friction signals the Supervisor delivers
to tiles. Silence is approval.
"""
from __future__ import annotations


class Interface:
    async def say(self, message) -> None: ...

    async def listen(self): ...

    def friction_from(self, observation):
        """Classify a reaction into a friction signal (reversal / repeat / remark)."""
        ...
