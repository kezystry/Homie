"""Wake governance — see the cortex's wake decisions, calibrate them to THIS home,
and cap them. Turns C8's unmeasured "~95% asleep" into a measured, enforced bound.

Three cooperating pieces, all PURE and EVENT-CLOCKED (driven by event timestamps,
never wall-clock, `Math.random`, or anything non-deterministic) so that replaying a
fixed event log reproduces bit-identical counts — the property the audit asked for:

  * `SurpriseGate`  — *calibrate it.* "Rare relative to this home", not below a magic
    global constant. A per-zone running low-rate quantile decides what counts as
    unusual; a global floor is the cold-start safety net before a zone has evidence.
  * `WakeBudget`    — *cap it.* A token bucket over wakes (N/hour, M/day) plus
    exponential backoff for a `(zone, topic)` the model keeps shrugging at. Safety and
    chat wakes bypass it entirely. Over-budget wakes are DEFERRED, never silently
    dropped; the lowest-surprise candidates shed first (the caller orders them).
  * `WakeLedger`    — *see it.* Counts every gate evaluation and reports the real
    asleep-fraction as a number, so the always-on energy premise is falsifiable.

`core/reason.py` composes the three; this module holds no bus and no I/O.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

# Default knobs. Deliberately generous so a single moment always wakes (the bucket
# starts full) — the budget only bites under a sustained flood, which is exactly C8's
# cold-start wake-storm.
WAKE_FLOOR = 0.1          # events/day: always-surprising floor (safety net for cold start)
SURPRISE_QUANTILE = 0.2   # a rate in a zone's low fifth is "rare relative to this home"
CALIB_WINDOW = 240        # recent established-rate samples kept per zone for calibration
CALIB_MIN = 24            # samples before calibration overrides the bare floor
BUDGET_PER_HOUR = 12      # token-bucket capacity / refill (wakes per hour)
BUDGET_PER_DAY = 120      # hard daily ceiling on wakes
BACKOFF_BASE = 300.0      # seconds a (zone,topic) is muted after one do-nothing wake
BACKOFF_CAP = 21600.0     # ...doubling up to 6h, after which it re-probes


@dataclass(frozen=True)
class WakeDecision:
    """One evaluation of the wake gate — the unit the ledger counts and the cortex
    emits as a `wake.decision` event. `fired` means the model was actually woken;
    `deferred` means the moment WAS surprising but the budget/backoff shed it — a
    recorded decision, never a silent drop. `outcome` is the human-readable reason."""

    topic: str
    zone: str | None
    hour: int
    rate: float
    novel: bool
    surprising: bool
    fired: bool
    deferred: bool
    outcome: str  # "routine" | "fired" | "exempt" | "budget" | "backoff" | "coalesced"


class SurpriseGate:
    """Per-zone calibrated novelty. A moment is surprising when it is genuinely novel,
    or its rate falls below the zone's calibrated low-rate threshold. The threshold is
    `max(floor, low-quantile of recent established rates)`: the floor guarantees a
    minimum sensitivity (the safety net), and calibration only ever RAISES the bar to
    match a home that is more regular than the global constant assumed."""

    def __init__(self, *, quantile: float = SURPRISE_QUANTILE, window: int = CALIB_WINDOW,
                 min_samples: int = CALIB_MIN, floor: float = WAKE_FLOOR) -> None:
        self.quantile = quantile
        self.window = window
        self.min_samples = min_samples
        self.floor = floor
        self._rates: dict[str | None, deque] = {}

    def observe(self, key: str | None, exp) -> None:
        """Feed an evaluated expectation into the zone's distribution. Novel sightings
        carry no rate and are not samples — calibration is about how often the things
        we DO know about happen here."""
        if getattr(exp, "novel", False):
            return
        dq = self._rates.get(key)
        if dq is None:
            dq = self._rates[key] = deque(maxlen=self.window)
        dq.append(float(getattr(exp, "rate", 0.0)))

    def threshold(self, key: str | None) -> float:
        dq = self._rates.get(key)
        if dq is None or len(dq) < self.min_samples:
            return self.floor  # cold start: the bare floor is the only honest signal
        ordered = sorted(dq)
        idx = min(len(ordered) - 1, int(self.quantile * len(ordered)))
        return max(self.floor, ordered[idx])

    def is_surprising(self, exp, key: str | None) -> bool:
        if getattr(exp, "novel", False):
            return True
        return float(getattr(exp, "rate", 0.0)) < self.threshold(key)


class WakeBudget:
    """A token bucket over wakes, clocked by EVENT time so it is replay-deterministic.
    `allow(ts)` spends a token if one has accrued and the daily ceiling is not hit.
    Backoff mutes a `(key, topic)` for an exponentially growing window each time the
    model wakes and does nothing, resetting the instant it acts — so a chatty-but-idle
    corner of the house stops costing wakes without ever going permanently deaf (the
    window is capped, after which it re-probes)."""

    def __init__(self, *, per_hour: float = BUDGET_PER_HOUR, per_day: int = BUDGET_PER_DAY,
                 backoff_base: float = BACKOFF_BASE, backoff_cap: float = BACKOFF_CAP) -> None:
        self.capacity = float(per_hour)
        self.refill_per_sec = per_hour / 3600.0
        self.tokens = float(per_hour)  # start full: the first wake is always free
        self.per_day = per_day
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._last_ts: float | None = None
        self._day: int | None = None
        self._day_count = 0
        self._idle: dict[tuple, int] = {}         # consecutive do-nothings per (key, topic)
        self._muted_until: dict[tuple, float] = {}

    def _refill(self, ts: float) -> None:
        if self._last_ts is None:
            self._last_ts = ts
            return
        if ts > self._last_ts:
            self.tokens = min(self.capacity, self.tokens + (ts - self._last_ts) * self.refill_per_sec)
            self._last_ts = ts

    def muted(self, key: str | None, topic: str, ts: float) -> bool:
        until = self._muted_until.get((key, topic))
        return until is not None and ts < until

    def allow(self, ts: float) -> bool:
        """Spend a token if available and under the daily ceiling. Does NOT consider
        backoff — the caller checks `muted()` first so a muted wake never burns budget."""
        self._refill(ts)
        day = int(ts // 86400)
        if day != self._day:
            self._day, self._day_count = day, 0
        if self._day_count >= self.per_day:
            return False
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            self._day_count += 1
            return True
        return False

    def note_outcome(self, key: str | None, topic: str, ts: float, *, did_something: bool) -> None:
        k = (key, topic)
        if did_something:
            self._idle.pop(k, None)
            self._muted_until.pop(k, None)
            return
        n = self._idle.get(k, 0) + 1
        self._idle[k] = n
        window = min(self.backoff_cap, self.backoff_base * (2 ** (n - 1)))
        self._muted_until[k] = ts + window


class WakeLedger:
    """Counts every wake-gate evaluation and reports the asleep-fraction as a real
    number. Pure integer accumulation over the decision stream → replaying a fixed log
    yields bit-identical counts (`test_ledger_counts_are_replay_stable`). Keeps a
    bounded tail of recent decisions for the cockpit; holds no bus."""

    def __init__(self, *, keep: int = 256) -> None:
        self.total = 0
        self.surprising = 0
        self.fired = 0
        self.deferred = 0
        self.outcomes: Counter = Counter()
        self.recent: deque = deque(maxlen=keep)

    def record(self, decision: WakeDecision) -> None:
        self.total += 1
        self.surprising += int(decision.surprising)
        self.fired += int(decision.fired)
        self.deferred += int(decision.deferred)
        self.outcomes[decision.outcome] += 1
        self.recent.append(decision)

    def asleep_fraction(self) -> float:
        """Fraction of evaluations that did NOT wake the model. 1.0 until proven
        otherwise — the number the energy premise stands or falls on."""
        if self.total == 0:
            return 1.0
        return 1.0 - self.fired / self.total

    def snapshot(self) -> dict:
        """A flat, render-ready summary for the cockpit / morning note."""
        return {
            "evaluations": self.total,
            "surprising": self.surprising,
            "fired": self.fired,
            "deferred": self.deferred,
            "asleep_fraction": round(self.asleep_fraction(), 4),
            "outcomes": dict(self.outcomes),
        }
