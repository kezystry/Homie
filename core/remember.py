"""Remember — Behavioral Analysis, the heart.

Persists events into a pattern-of-life model and answers "what is normal?" for a
given time, zone, and context. Every other part of the system consults it.
"""
from __future__ import annotations


class Remember:
    async def record(self, event) -> None: ...

    async def normal(self, context):
        """Return the expected pattern for a context, for Reason to compare against."""
        ...
