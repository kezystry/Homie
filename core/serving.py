"""Serving discipline for the on-demand heavy cortex (M6).

The reasoning model is an 8B served by llama-server on the RTX 3060 desktop, which the
owner keeps in suspend-to-RAM so it wakes fast (Wake-on-LAN) and sleeps when idle. Two
disciplines make that pleasant instead of clunky, and both are pure/testable here — the
*mechanism* (the HTTP call, the WoL packet, the GPU suspend) lives in deploy/ and the OS,
but the *policy* lives here so it is exercised by the suite with no GPU and no network:

  * **LatencySLO** — every wake decision is timed; the SLO tracks a rolling window so the
    status page can show p50/p95 and a breach rate. A brain that has gone slow becomes a
    visible number, not a vague feeling. It never changes what Homie decides — it only
    measures, so honesty is free.
  * **WarmPolicy** — decides whether to keep the model warm or let the GPU cool, from the
    measured wake cadence (M3). A cold model pays a load penalty on the next wake; a warm
    GPU costs power. We keep warm only briefly around real activity (so a burst doesn't
    re-pay cold-start each time) and otherwise let the desktop sleep.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class LatencySLO:
    """A rolling record of how long the cortex takes to answer, against a target budget.

    Pure bookkeeping: `record(ms)` adds a sample; `p50`/`p95` summarize the window;
    `breach_rate` is the fraction over budget. The budget is the felt "quick" target for
    one wake decision — generous by default (the GPU is on-box), tunable per deployment."""

    def __init__(self, budget_ms: float = 4000.0, *, window: int = 50) -> None:
        self.budget_ms = budget_ms
        self.window = window
        self._samples: deque[float] = deque(maxlen=window)
        self.total = 0
        self.breaches = 0

    def met(self, ms: float) -> bool:
        return ms <= self.budget_ms

    def record(self, ms: float) -> bool:
        """Record one latency sample; returns whether it met the budget."""
        self._samples.append(ms)
        self.total += 1
        ok = self.met(ms)
        if not ok:
            self.breaches += 1
        return ok

    def _quantile(self, q: float) -> float | None:
        if not self._samples:
            return None
        ordered = sorted(self._samples)
        # nearest-rank: index = ceil(q*n)-1, clamped — exact and tie-stable for a tiny window.
        idx = min(len(ordered) - 1, max(0, -(-int(q * len(ordered) * 100) // 100) - 1))
        return ordered[idx]

    def p50(self) -> float | None:
        return self._quantile(0.50)

    def p95(self) -> float | None:
        return self._quantile(0.95)

    def breach_rate(self) -> float:
        return self.breaches / self.total if self.total else 0.0

    def summary(self) -> dict:
        """A small JSON-safe snapshot for telemetry / the status page."""
        return {
            "budget_ms": self.budget_ms,
            "samples": len(self._samples),
            "total": self.total,
            "p50_ms": self.p50(),
            "p95_ms": self.p95(),
            "breach_rate": round(self.breach_rate(), 4),
        }


class WarmPolicy:
    """Keep-warm decision for the heavy GPU model, driven by recent wake cadence.

    After each real wake we stay warm for `keep_warm_s`, so a flurry of activity (someone
    moving through the house) doesn't re-pay the cold-start load on every event. When the
    last wake is older than the window, `is_warm` is False — the desktop is free to sleep.
    `recommend` adapts the window upward when wakes are arriving close together (an active
    stretch) and back down when they're sparse, bounded by [keep_warm_s, max_warm_s]."""

    def __init__(self, keep_warm_s: float = 300.0, *, max_warm_s: float = 1800.0,
                 now: Callable[[], float] = time.monotonic) -> None:
        self.base_warm_s = keep_warm_s
        self.max_warm_s = max_warm_s
        self._now = now
        self._last_wake: float | None = None
        self._prev_wake: float | None = None
        self._window_s = keep_warm_s

    def note_wake(self, ts: float | None = None) -> None:
        """Record that the cortex just fired (a real wake)."""
        t = self._now() if ts is None else ts
        if self._last_wake is not None:
            gap = t - self._last_wake
            # Close-together wakes widen the warm window; sparse ones relax it back.
            if gap <= self.base_warm_s:
                self._window_s = min(self.max_warm_s, self._window_s * 1.5)
            else:
                self._window_s = self.base_warm_s
        self._prev_wake, self._last_wake = self._last_wake, t

    def warm_window_s(self) -> float:
        return self._window_s

    def is_warm(self, ts: float | None = None) -> bool:
        """True if the model should currently be kept loaded (recent enough wake)."""
        if self._last_wake is None:
            return False
        t = self._now() if ts is None else ts
        return (t - self._last_wake) <= self._window_s

    def summary(self, ts: float | None = None) -> dict:
        return {
            "warm": self.is_warm(ts),
            "warm_window_s": round(self._window_s, 1),
            "last_wake": self._last_wake,
        }
