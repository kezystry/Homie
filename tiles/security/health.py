"""Security — self-healing. Healthy as long as it can reach the pattern of life;
that check lives in the runtime (ctx.recall), so the tile itself is stateless."""
from __future__ import annotations


async def health(state) -> bool:
    return True
