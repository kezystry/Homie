"""Reason — the local LLM decision.

Weighs the current moment against Remember's notion of normal and decides what,
if anything, to do. Runs entirely on the reasoning node; nothing leaves the network.
"""
from __future__ import annotations


class Reason:
    async def decide(self, now, normal): ...
