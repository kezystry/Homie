"""Remember — Behavioral Analysis, the heart.

Builds a pattern of life from the event stream and answers "what is normal?" for
a given topic, zone, and time. It reads the same append-only log the bus writes
(bootstrap on start) and updates live by subscribing — one log, two readers.

The model is an exponentially-decayed estimate: per (topic, zone) it holds a
decayed event mass per hour-of-day bucket and a decayed distinct-day mass, so an
expectation reads as ~events/day at that hour over a rolling ~30-day window. Old
behaviour fades (the household changes); never/no-longer-seen keys are `novel`.
Decay is memoryless (lazy on write/read to an injected timestamp — never the wall
clock), so replaying the same log is bit-identical. Security and Self-Learning
consume this; thresholds/policy live in the caller.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from core.bus import _compile
from core.tile import Event

log = logging.getLogger("homie.remember")

HOURS = 24
HALF_LIFE_DAYS = 30.0
DAY_SECONDS = 86400.0
LAMBDA = math.log(2) / (HALF_LIFE_DAYS * DAY_SECONDS)  # per-second decay rate
EPS = 1e-3  # prune threshold on decayed day-mass
NMIN_DAYS = 3.0  # evidence floor: below this many decayed active-days, a belief is "still
                 # learning", never stated as fact (kills "a coincidence renders as a fact")
SNAPSHOT_VERSION = 3

Key = tuple[str, str | None]


@dataclass(frozen=True)
class Expectation:
    rate: float  # ~events/day at this (key, hour) over the decay window — the cortex's
                 # rarity signal (LOW = surprising). UNCHANGED meaning; consumers rely on it.
    count: float  # decayed event mass in the bucket (evidence, not a raw count)
    days: float  # decayed effective days of evidence for the key
    novel: bool  # the (topic, zone) was never observed (or has fully decayed away)
    # --- honest belief probability (Phase B) -------------------------------------- #
    prob: float = 0.0   # P(this routine fires at this hour on a given day) ∈ [0,1]. The
                        # numerator is decayed DISTINCT days present at this hour; the
                        # denominator is the GLOBAL decayed active-day count — so a stopped
                        # routine mean-reverts (FIX-2) and the value can never exceed 1 (FIX-1).
    gdays: float = 0.0  # decayed global active-days (the shared denominator / evidence weight)
    firm: bool = False  # gdays >= NMIN_DAYS — is there enough evidence to state prob as a belief?


def _zone(event: Event) -> str | None:
    return event.payload.get("zone")


class PatternModel:
    """Per-(topic, zone): a 24-hour decayed weight vector + a decayed day-mass.
    `last_update` is one timestamp per key — decay is memoryless, so ageing the
    whole vector to a common time equals per-bucket bookkeeping at 1/24 the cost."""

    def __init__(self, tz: str | None = None) -> None:
        self._tz = tz  # IANA name (e.g. "Europe/Berlin"); None = host local time
        self._zone = ZoneInfo(tz) if tz else None
        self._w: dict[Key, list[float]] = {}  # decayed event mass per hour (rate numerator)
        self._days: dict[Key, float] = {}  # decayed distinct-day mass (rate denominator)
        self._last: dict[Key, float] = {}  # last update, epoch seconds
        self._lastd: dict[Key, str] = {}  # ISO date of last observation (distinct-day gate)
        # --- honest-probability stats (Phase B) ----------------------------------- #
        # _present[key][h] = decayed count of DISTINCT days this key fired at hour h (at most
        # +1 per day per hour). _present_today[key] gates that +1 within the current day.
        self._present: dict[Key, list[float]] = {}
        self._present_today: dict[Key, list[int]] = {}
        # The GLOBAL active-day denominator: distinct days the home produced ANY perception.
        # Shared across keys so a routine that STOPS still sees the denominator grow → its
        # prob mean-reverts in days (FIX-2), and prob = present/global ≤ 1 always (FIX-1).
        self._gdays: float = 0.0
        self._glast: float | None = None
        self._glastd: str | None = None

    def _dt(self, ts: float) -> datetime:
        """Local time in the pinned zone — so hour buckets are stable across hosts."""
        return datetime.fromtimestamp(ts, self._zone) if self._zone else datetime.fromtimestamp(ts)

    @staticmethod
    def _factor(dt: float) -> float:
        return math.exp(-LAMBDA * max(0.0, dt))  # clamp: a replayed clock never grows mass

    def observe(self, event: Event) -> None:
        key = (event.topic, _zone(event))
        t = event.ts
        w = self._w.setdefault(key, [0.0] * HOURS)
        present = self._present.setdefault(key, [0.0] * HOURS)
        d = self._factor(t - self._last.get(key, t))  # decay existing mass to event time
        for j in range(HOURS):
            w[j] *= d
            present[j] *= d
        self._days[key] = self._days.get(key, 0.0) * d
        when = self._dt(t)
        today = when.date().isoformat()
        if self._lastd.get(key) != today:  # rate denominator counts distinct OBSERVED days
            self._days[key] += 1.0
            self._lastd[key] = today
            self._present_today[key] = []   # a new day: this key may add one presence/hour
        w[when.hour] += 1.0  # rate numerator counts every event
        if when.hour not in self._present_today.setdefault(key, []):
            present[when.hour] += 1.0       # prob numerator: at most one present-day per hour
            self._present_today[key].append(when.hour)
        self._last[key] = max(self._last.get(key, t), t)  # never move the clock backward
        self._observe_global(t, today)

    def _observe_global(self, t: float, today: str) -> None:
        """Tick the shared active-day denominator: the home was alive today. Decayed to the
        common clock so prob's denominator ages with the same half-life as its numerator."""
        gd = self._factor(t - (self._glast if self._glast is not None else t))
        self._gdays *= gd
        if self._glastd != today:
            self._gdays += 1.0
            self._glastd = today
        self._glast = max(self._glast, t) if self._glast is not None else t

    def expectation(self, topic: str, zone: str | None, when: float) -> Expectation:
        key = (topic, zone)
        if key not in self._w:
            return Expectation(rate=0.0, count=0.0, days=0.0, novel=True)
        hour = self._dt(when).hour
        d = self._factor(when - self._last[key])  # decay a scratch copy; no mutation
        count = self._w[key][hour] * d
        days = self._days[key] * d
        rate = count / days if days > 0.0 else 0.0  # d cancels: a stopped pattern's rate holds
        # The honest belief probability, on the GLOBAL active-day denominator (decayed to the
        # same `when`). present ≤ global at every accrual and global ages no faster, so
        # prob ∈ [0,1] by construction; clamp only as a floating-point guard.
        present = self._present.get(key, [0.0] * HOURS)[hour] * d
        gdays = self._gdays * self._factor(when - self._glast) if self._glast is not None else 0.0
        prob = min(1.0, present / gdays) if gdays > 0.0 else 0.0
        return Expectation(rate=rate, count=count, days=days, novel=False,
                           prob=prob, gdays=gdays, firm=gdays >= NMIN_DAYS)

    def keys(self) -> list[Key]:
        """The (topic, zone) keys currently held. Pure read."""
        return list(self._w)

    def decayed_weights(self, key: Key, now: float) -> list[float]:
        """The 24-hour weight vector for `key`, aged to `now`. Pure read — a scratch
        copy, never mutates. Returns all-zeros for an unknown key."""
        w = self._w.get(key)
        if not w:
            return [0.0] * HOURS
        d = self._factor(now - self._last[key])
        return [x * d for x in w]

    def last_update(self, key: Key) -> float | None:
        """Epoch of the most recent observation for `key` (its 'last seen')."""
        return self._last.get(key)

    def belief(self, key: Key, now: float) -> dict | None:
        """The single most reliable hour for `key` and the HONEST probability it fires then,
        on the global active-day denominator. Pure read (a scratch decay, no mutation).
        Returns None for an unknown/faded key or before any global evidence exists."""
        if key not in self._w or self._glast is None:
            return None
        d = self._factor(now - self._last[key])
        present = [x * d for x in self._present.get(key, [0.0] * HOURS)]
        gdays = self._gdays * self._factor(now - self._glast)
        if gdays <= 0.0 or not any(present):
            return None
        hour = max(range(HOURS), key=lambda h: present[h])
        return {"hour": hour, "prob": min(1.0, present[hour] / gdays),
                "gdays": gdays, "firm": gdays >= NMIN_DAYS}

    def decay(self, now: float) -> None:
        """Realize decay on every key to `now` and prune those that have faded
        away (→ novel again). Idempotent at a fixed `now`. Called nightly."""
        for key in list(self._w):
            d = self._factor(now - self._last[key])
            w = self._w[key]
            present = self._present.get(key, [0.0] * HOURS)
            for j in range(HOURS):
                w[j] = w[j] * d if w[j] * d >= EPS else 0.0
                present[j] = present[j] * d if present[j] * d >= EPS else 0.0
            self._days[key] *= d
            self._last[key] = now
            if self._days[key] < EPS:
                for store in (self._w, self._days, self._last, self._lastd,
                              self._present, self._present_today):
                    store.pop(key, None)
        # Age the global denominator too — without this a quiet home's gdays would never fade
        # and prob would understate a returning routine.
        if self._glast is not None:
            self._gdays *= self._factor(now - self._glast)
            self._glast = now

    def snapshot(self) -> dict:
        """Serialize to a JSON-safe v3 dict. Pure read — never decays or mutates."""
        keys = []
        for key, w in self._w.items():
            topic, zone = key
            keys.append(
                {
                    "topic": topic,
                    "zone": zone,
                    "weights": [round(x, 6) for x in w],
                    "days_mass": round(self._days[key], 6),
                    "last_update": self._last[key],
                    "last_obs_date": self._lastd.get(key),
                    # Phase B: the presence numerator + the per-day hour gate, so a mid-day
                    # restore does not double-count today's presence (determinism).
                    "present": [round(x, 6) for x in self._present.get(key, [0.0] * HOURS)],
                    "present_today": list(self._present_today.get(key, [])),
                }
            )
        return {"version": SNAPSHOT_VERSION, "hours": HOURS, "half_life_days": HALF_LIFE_DAYS,
                "tz": self._tz, "keys": keys,
                "global": {"days": round(self._gdays, 6), "last": self._glast, "last_date": self._glastd}}

    def restore(self, snap: dict) -> None:
        snap_tz = snap.get("tz")
        if snap_tz != self._tz:  # buckets were frozen in the old zone; flag the drift
            log.warning("remember: snapshot tz %r != configured tz %r — hour buckets may be offset", snap_tz, self._tz)
        version = snap.get("version", 1)
        if version == 1:
            self._restore_v1(snap)
        elif version == 2:
            self._restore_v2(snap)
            self._seed_global_from_legacy()
        elif version == SNAPSHOT_VERSION:
            self._restore_v3(snap)
        else:  # future format on an older binary — caller falls back to log replay
            raise ValueError(f"unknown snapshot version {version}")

    def _restore_v2(self, snap: dict) -> None:
        for k in snap.get("keys", []):
            weights = [float(x) for x in k["weights"]]
            days = float(k["days_mass"])
            last = float(k["last_update"])
            if not (all(map(math.isfinite, weights)) and math.isfinite(days) and math.isfinite(last)):
                log.warning("remember: skipping non-finite snapshot key %r", k.get("topic"))
                continue
            key = (k["topic"], k["zone"])
            self._w[key] = weights
            self._days[key] = days
            self._last[key] = last
            self._lastd[key] = k.get("last_obs_date")
            # v2 has no presence numerator. Seed it best-effort and CAPPED at the day mass so
            # prob ≤ 1 holds from the first read; it self-corrects as real events arrive.
            self._present[key] = [min(x, days) for x in weights]
            self._present_today[key] = []

    def _restore_v3(self, snap: dict) -> None:
        self._restore_v2(snap)  # the per-key weights/days/last carry over unchanged
        for k in snap.get("keys", []):
            key = (k["topic"], k["zone"])
            if key not in self._w:
                continue  # was skipped as non-finite
            present = [float(x) for x in k.get("present", [0.0] * HOURS)]
            if all(map(math.isfinite, present)):
                self._present[key] = present
            self._present_today[key] = [int(h) for h in k.get("present_today", [])]
        g = snap.get("global", {})
        gd, gl = g.get("days", 0.0), g.get("last")
        if isinstance(gd, (int, float)) and math.isfinite(gd):
            self._gdays = float(gd)
        self._glast = float(gl) if isinstance(gl, (int, float)) and math.isfinite(gl) else None
        self._glastd = g.get("last_date")

    def _seed_global_from_legacy(self) -> None:
        """Migrating a pre-Phase-B snapshot: there is no global active-day count. The most
        active key's distinct-day mass is a sound lower bound on active days, so seed gdays
        from it (anchored at the latest observation). prob then starts slightly HIGH and
        relaxes toward truth as real days accrue — honest and rate-preserving enough."""
        if not self._days:
            return
        self._gdays = max(self._days.values())
        self._glast = max(self._last.values())
        self._glastd = max((d for d in self._lastd.values() if d), default=None)

    def _restore_v1(self, snap: dict) -> None:
        """Migrate the old {counts:[24 ints], dates:[iso...]} shape forward,
        rate-preserving: stamp last_update at the LAST observed date (not now), so
        the first decay() ages stale routines instead of treating them as fresh."""
        for k in snap.get("keys", []):
            dates = k.get("dates", [])
            if not dates:
                continue
            key = (k["topic"], k["zone"])
            last_date = max(dates)
            self._w[key] = [float(c) for c in k["counts"]]
            self._days[key] = float(len(dates))  # old cardinality is the undecayed denominator
            self._last[key] = datetime.fromisoformat(last_date).timestamp()
            self._lastd[key] = last_date


class Remember:
    #: perception topics the pattern of life is built from (not internal chatter)
    PERCEPTION = ("presence.**", "motion.**", "occupancy.**")

    def __init__(self, off_zones=frozenset()) -> None:
        self.model = PatternModel(tz=os.environ.get("HOMIE_TZ"))  # pin the home's zone if set
        # OFF-fence at INGEST (Charter law 4): an off-limits zone leaves no trace in the model,
        # not just no render. Defence-in-depth — the perception allowlist is the first gate, this
        # is the second, so a misconfig or a new perception path can't seed off-limits data.
        self.off_zones = frozenset(off_zones)

    async def record(self, event: Event) -> None:
        # Evaluate-then-commit (C4): anomaly evaluators (Security, Reason) must judge
        # an event against history WITHOUT it, or the event masks its own novelty.
        # TWO things guarantee that and BOTH are needed:
        #   1. Remember attaches to the bus LAST (after the tiles) — see build_daemon —
        #      so for a given event its drain task is scheduled after the evaluators'.
        #   2. We defer the actual commit by one event-loop tick. An evaluator runs
        #      through the tile channel, whose `asyncio.wait_for` yields the loop; that
        #      yield would otherwise let this observe land *before* the evaluator's
        #      `ctx.recall` reads the model. The one-tick defer keeps the commit behind
        #      the (synchronous-to-recall) in-process evaluators.
        # This is a one-tick ordering nicety, NOT a two-phase bus barrier (the audit's
        # anti-goal): drain() still waits for the commit, so post-drain state is intact.
        await asyncio.sleep(0)
        if self.off_zones:
            zone = (event.payload or {}).get("zone")
            if zone in self.off_zones:
                return                          # off-limits → never enters the pattern of life
        self.model.observe(event)

    async def normal(self, topic: str, zone: str | None, when: float) -> Expectation:
        """What is expected for this topic/zone at this time."""
        return self.model.expectation(topic, zone, when)

    def decay(self, now: float) -> None:
        """Age + prune the pattern of life (the nightly consolidation calls this)."""
        self.model.decay(now)

    # -- read-only pattern-of-life queries (the anchor voice answers from these) -- #
    def zones(self) -> list[str]:
        """Distinct zones the pattern of life has ever seen, sorted."""
        return sorted({z for (_t, z) in self.model.keys() if z})

    def pattern_count(self) -> int:
        """How many (topic, zone) patterns are currently held."""
        return len(self.model.keys())

    def describe_zone(self, zone: str, now: float) -> dict | None:
        """A small human-facing summary of a zone's pattern of life: the busiest
        hour-of-day (aggregated across topics) and when it was last seen. Returns
        None if the zone is unknown, or {"hour": None, ...} if it has fully decayed."""
        keys = [k for k in self.model.keys() if k[1] == zone]
        if not keys:
            return None
        hours = [0.0] * HOURS
        last: float | None = None
        for k in keys:
            for j, x in enumerate(self.model.decayed_weights(k, now)):
                hours[j] += x
            lu = self.model.last_update(k)
            if lu is not None:
                last = lu if last is None else max(last, lu)
        peak = hours.index(max(hours)) if sum(hours) > 0.0 else None
        return {"hour": peak, "last_seen": last}

    def beliefs(self, now: float, *, min_prob: float = 0.3) -> list[dict]:
        """The plain, FIRM things Homie believes about the household — for the 'What Homie
        Knows' page. One row per (topic, zone): its most reliable hour, the honest
        probability, and the evidence behind it. Only FIRM beliefs (>= NMIN_DAYS of evidence)
        above `min_prob` are returned, strongest first — a coincidence never shows as a fact.
        """
        rows = []
        for key in self.model.keys():
            b = self.model.belief(key, now)
            if b is None or not b["firm"] or b["prob"] < min_prob:
                continue
            topic, zone = key
            rows.append({"topic": topic, "zone": zone, **b})
        rows.sort(key=lambda r: (-r["prob"], -r["gdays"], r["topic"], r["zone"] or ""))
        return rows

    def snapshot(self) -> dict:
        """The current pattern of life, for the bus to persist during compaction."""
        return self.model.snapshot()

    def restore(self, snap: dict) -> None:
        self.model.restore(snap)

    def bootstrap(self, bus) -> None:
        """Rebuild the model from the bus's durability log — the log is the memory.

        Loads the compaction snapshot (if any), then folds the events not yet
        covered by it (uncovered segments + the live tail). Only perception events
        feed the pattern of life, matching attach(). A snapshot we can't read (an
        unknown/future version) is skipped — we fall back to folding what's logged.
        """
        snap = bus.load_snapshot()
        if snap is not None:
            try:
                self.model.restore(snap)
            except Exception:
                log.warning("remember: unreadable snapshot; rebuilding from the log")
        patterns = [_compile(p) for p in self.PERCEPTION]
        for event in bus.pending_events():
            if any(p.match(event.topic) for p in patterns):
                self.model.observe(event)

    def attach(self, bus) -> None:
        """Record perception events live, on top of the bootstrap history.

        Ordering contract: anomaly evaluation (Security/Reason) must judge an event
        against *prior* history. A consumer that both evaluates and learns from the
        same event must evaluate first, then commit — else the event masks its own
        novelty. Remember therefore lags evaluation by design.
        """
        for topic in self.PERCEPTION:
            bus.subscribe(topic, self.record, owner="core:remember")
