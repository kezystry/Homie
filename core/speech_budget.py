"""Speech governance — the muzzle that must exist before the mouths.

The brainstorm's red team caught the one hole the shipped code actually had: nothing
limited how often Homie *talks* to the owner. The wake budget (`core/wake_ledger.py`)
caps GPU *thinks*, not owner-facing *speech* — a cheap anchor reply or a tile's
`ctx.speak` reaches the human with no governor at all. The owner named "a nag" the single
worst outcome, and the roadmap was about to bolt on ~8 new speaking features. So this is
Phase A: ONE global, cross-tile cap on proactive speech, built BEFORE any second mouth.

The axis is **social restraint** (owner-facing utterances per day), NOT GPU economy — the
two are orthogonal. One wake can emit zero or several spoken lines; a no-wake anchor reply
still interrupts. So this is a NEW component, not a re-pointed wake bucket.

Like the wake ledger, everything here is PURE and EVENT-CLOCKED (driven by event
timestamps, never wall-clock or randomness) so replaying a fixed event log reproduces
bit-identical counts. Three cooperating pieces:

  * `AdaptiveAllowance` — *learn it.* There is NO fixed daily cap. The allowance starts at a
    sensible default and LEARNS: every time the owner mutes Homie (a "you're talking too much"
    signal) the allowance shrinks; every day Homie speaks and the owner does NOT mute, it grows
    a little. So it finds the owner's tolerance on its own instead of obeying a hand-set number.
  * `SpeechBudget` — *pace it.* A token bucket over proactive utterances (a small per-hour burst
    capacity so a day's lines can't all land at once) whose daily ceiling is the LEARNED
    allowance. Safety/summons speech bypasses it entirely. Over-budget lines defer to the recap
    as a LOSSY count — most die unspoken (external audit §4.1: silence is the right default).
  * `Mute`         — *the owner's own hand.* An everyday "quiet for an hour" / "minimal
    today" the owner sets in the moment, distinct from guest/privacy semantics and
    instantly reversible. The fastest nag-kill is a mute the owner controls.
  * `SpeechLedger` — *see it.* Counts every decision (spoken / deferred / exempt) so the
    "how chatty was I" number is falsifiable and feeds the recap's relief valve.

`SpeechGovernor` composes the three into one `decide(...)` call; `core/voice.py` wraps it
with the bus (subscribes `interface.say`, emits `interface.spoken` or `speech.deferred`).
This module holds no bus and no I/O.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

# Default knobs. There is NO fixed daily cap — Homie LEARNS how chatty to be from the owner's
# reactions (the `AdaptiveAllowance` below). These are only the STARTING point and the bounds it
# learns within; the per-hour capacity smooths bursts so a day's lines can't all land at once.
PROACTIVE_PER_DAY_START = 6   # where the learned allowance starts on day one
PROACTIVE_PER_DAY_MIN = 1     # it never silences itself entirely (a real alert path always exists)
PROACTIVE_PER_DAY_MAX = 14    # ...nor lets itself become a firehose, however tolerant the owner
PROACTIVE_PER_HOUR = 2.0      # token-bucket burst capacity / refill rate (lines per hour)
SHRINK = 0.6                  # a "too chatty" signal (a mute) multiplies the allowance down
GROW = 0.5                    # a tolerated day (spoke, no mute) nudges it back up
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600.0

# Speech that must never be throttled: a genuine alert, a hazard, or a direct answer to a
# summons. The owner's nag fear is about UNSOLICITED chatter; these are neither chatter nor
# optional. Anything not in this set is "proactive" and spends from the budget.
EXEMPT_KINDS = frozenset({"safety", "alert", "emergency", "summons"})


def is_exempt(kind: str) -> bool:
    """True when this utterance bypasses the budget and the mute entirely."""
    return kind in EXEMPT_KINDS


@dataclass(frozen=True)
class SpeechDecision:
    """One evaluation of the speech gate — the unit the ledger counts and `core/voice.py`
    turns into an `interface.spoken` (the owner hears it) or a `speech.deferred` (it does
    NOT reach the owner now; the recap may show it as part of a lossy count). `spoken` and
    `deferred` are mutually exclusive. `outcome` is the human-readable reason."""

    kind: str
    source: str | None
    spoken: bool
    deferred: bool
    outcome: str  # "exempt" | "spoken" | "budget" | "muted"


class SpeechBudget:
    """A token bucket over PROACTIVE utterances, clocked by EVENT time so it is
    replay-deterministic. `allow(ts)` spends a token if one has accrued and the daily
    ceiling is not yet hit. Starts full so the first line of the day is always free — the
    budget only bites a sustained flood, which is exactly the nag it exists to stop."""

    def __init__(self, *, per_hour: float = PROACTIVE_PER_HOUR, per_day: int = PROACTIVE_PER_DAY_START) -> None:
        self.capacity = float(per_hour)
        self.refill_per_sec = per_hour / SECONDS_PER_HOUR
        self.tokens = float(per_hour)   # start full: the first proactive line is free
        self.per_day = per_day
        self._last_ts: float | None = None
        self._day: int | None = None
        self._day_count = 0

    def _refill(self, ts: float) -> None:
        if self._last_ts is None:
            self._last_ts = ts
            return
        if ts > self._last_ts:
            self.tokens = min(self.capacity, self.tokens + (ts - self._last_ts) * self.refill_per_sec)
            self._last_ts = ts

    def day_count(self, ts: float) -> int:
        """Proactive lines already spoken on this calendar day (event-time days)."""
        return self._day_count if int(ts // SECONDS_PER_DAY) == self._day else 0

    def remaining_today(self, ts: float) -> int:
        return max(0, self.per_day - self.day_count(ts))

    def allow(self, ts: float) -> bool:
        """Spend a token if one is available and the daily ceiling is not reached."""
        self._refill(ts)
        day = int(ts // SECONDS_PER_DAY)
        if day != self._day:
            self._day, self._day_count = day, 0
        if self._day_count >= self.per_day:
            return False
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            self._day_count += 1
            return True
        return False


class Mute:
    """The everyday owner mute: 'quiet for an hour' / 'minimal today'. A single quiet-until
    instant in event time, set by the owner and instantly reversible. Deliberately NOT the
    guest/privacy posture — this is just 'shush' and it only silences proactive speech
    (safety/summons stay exempt at the governor). Event-clocked like everything else."""

    def __init__(self) -> None:
        self.quiet_until: float | None = None

    def mute(self, ts: float, seconds: float) -> None:
        """Be quiet for `seconds` from `ts`. Extends, never shortens, an active window."""
        until = ts + max(0.0, float(seconds))
        if self.quiet_until is None or until > self.quiet_until:
            self.quiet_until = until

    def unmute(self) -> None:
        self.quiet_until = None

    def quiet(self, ts: float) -> bool:
        return self.quiet_until is not None and ts < self.quiet_until


class SpeechLedger:
    """Counts every speech-gate decision and reports how chatty Homie has been as a real
    number. Pure integer accumulation over the decision stream → replaying a fixed log
    yields bit-identical counts. Keeps a bounded tail for the cockpit; holds no bus."""

    def __init__(self, *, keep: int = 256) -> None:
        self.total = 0
        self.spoken = 0
        self.deferred = 0
        self.exempt = 0
        self.outcomes: Counter = Counter()
        self.recent: deque = deque(maxlen=keep)

    def record(self, decision: SpeechDecision) -> None:
        self.total += 1
        self.spoken += int(decision.spoken)
        self.deferred += int(decision.deferred)
        self.exempt += int(decision.outcome == "exempt")
        self.outcomes[decision.outcome] += 1
        self.recent.append(decision)

    def quiet_fraction(self) -> float:
        """Fraction of would-be proactive lines that did NOT reach the owner as fresh
        interruptions (deferred to the recap). 1.0 when nothing has been deferred."""
        proactive = self.total - self.exempt
        if proactive <= 0:
            return 1.0
        return self.deferred / proactive

    def snapshot(self) -> dict:
        """A flat, render-ready summary for the cockpit / morning recap relief valve."""
        return {
            "evaluations": self.total,
            "spoken": self.spoken,
            "deferred": self.deferred,
            "exempt": self.exempt,
            "outcomes": dict(self.outcomes),
        }


class AdaptiveAllowance:
    """Learns how many proactive lines/day the owner tolerates — there is no fixed cap.

    Event-clocked and deterministic like everything else. `too_chatty(ts)` (the owner muted, or
    dismissed a line) multiplies the allowance DOWN; a day that Homie spoke and the owner did
    NOT signal annoyance nudges it UP at the next day rollover. Bounded so it never silences
    itself entirely (a real alert path always exists) nor becomes a firehose."""

    def __init__(self, *, start: float = PROACTIVE_PER_DAY_START, lo: float = PROACTIVE_PER_DAY_MIN,
                 hi: float = PROACTIVE_PER_DAY_MAX, shrink: float = SHRINK, grow: float = GROW) -> None:
        self.value = float(start)
        self.lo, self.hi, self.shrink, self.grow = lo, hi, shrink, grow
        self._day: int | None = None
        self._spoke = False      # did Homie speak proactively this day?
        self._annoyed = False    # did the owner signal "too chatty" this day?

    def daily(self) -> int:
        """The current learned daily ceiling (never below 1)."""
        return max(1, round(self.value))

    def _roll(self, ts: float) -> None:
        day = int(ts // SECONDS_PER_DAY)
        if self._day is None:
            self._day = day
            return
        if day != self._day:
            if self._spoke and not self._annoyed:   # a tolerated day → earn a little more voice
                self.value = min(self.hi, self.value + self.grow)
            self._day, self._spoke, self._annoyed = day, False, False

    def note_spoke(self, ts: float) -> None:
        self._roll(ts)
        self._spoke = True

    def too_chatty(self, ts: float) -> None:
        """The owner told Homie to be quieter (a mute / a dismissed line). Learn from it."""
        self._roll(ts)
        self.value = max(self.lo, self.value * self.shrink)
        self._annoyed = True


class SpeechGovernor:
    """Composes the LEARNED allowance, the budget, the mute, and the ledger into one decision.
    Pure and event-clocked: `decide(ts, kind, source)` is a deterministic function of the inputs
    and the accumulated state. The order is deliberate — exempt speech is never muted or
    budgeted (a hazard must always be heard); the owner's mute outranks the budget (his explicit
    'shush' beats Homie's own restraint); the budget (paced by the learned allowance) is last."""

    def __init__(self, *, budget: SpeechBudget | None = None, mute: Mute | None = None,
                 ledger: SpeechLedger | None = None, allowance: AdaptiveAllowance | None = None) -> None:
        self.budget = budget or SpeechBudget()
        self.mute = mute or Mute()
        self.ledger = ledger or SpeechLedger()
        self.allowance = allowance or AdaptiveAllowance(start=self.budget.per_day)

    def note_too_chatty(self, ts: float) -> None:
        """Feed a 'you're talking too much' signal (a mute / dismissal) into the learning."""
        self.allowance.too_chatty(ts)

    def decide(self, ts: float, *, kind: str = "proactive", source: str | None = None) -> SpeechDecision:
        self.budget.per_day = self.allowance.daily()   # the ceiling is the LEARNED allowance
        if is_exempt(kind):
            d = SpeechDecision(kind, source, spoken=True, deferred=False, outcome="exempt")
        elif self.mute.quiet(ts):
            d = SpeechDecision(kind, source, spoken=False, deferred=True, outcome="muted")
        elif self.budget.allow(ts):
            self.allowance.note_spoke(ts)
            d = SpeechDecision(kind, source, spoken=True, deferred=False, outcome="spoken")
        else:
            d = SpeechDecision(kind, source, spoken=False, deferred=True, outcome="budget")
        self.ledger.record(d)
        return d
