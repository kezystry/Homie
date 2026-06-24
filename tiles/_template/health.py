"""Template tile — self-healing. Report fitness and recover from local faults.

Return False to have the Supervisor restart or quarantine this tile without
touching the rest of the colony.
"""
from __future__ import annotations


async def health(state) -> bool:
    return True
