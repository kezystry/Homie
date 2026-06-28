"""The Dream Journal (M7) — retrieval over the distilled GIST memory, into the cortex.

Two halves, both deterministic and model-free:
  * `gist.recall()` is a pure facet-overlap query over the existing GIST schemas — no embedder,
    no vector DB, no second store. An "episode" is just `line_text(s)`.
  * the cortex injects the recalled lines into `build_context`, so a wake decision is informed
    by what the home has learned.

The named acceptance test is `test_retrieval_changes_a_decision`: an A/B on ONE event where the
only difference is whether memory is wired — and the decision flips. Plus a selectivity check,
so the flip isn't a constant that trivially fires on everything, and a privacy invariant
(recalled lines are plain `render_brief` text — no embedding exists to leak).

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timezone

from core.bus import Bus
from core.gist import Beta, Schema, line_text, recall
from core.gist_store import event_tokens
from core.gist import daypart_of, daytype_of
from core.reason import Proposal, Reason, ToolCall
from core.remember import Expectation
from core.tile import Event

UTC = timezone.utc

# A firm "weekday evenings → Plex" line: n_eff = 8 days → firmness 3 (== the recall floor),
# confidence ~0.67 → present tense. line_text → "...you usually media in the plex."
PLEX = Schema(kind="rule", daytype="wd", daypart="eve", tokens=("media", "plex"),
              beta=Beta(a_q=8000, b_q=0))
SENTINEL = "media in the plex"           # the clause that line_text(PLEX) carries

# A weekday-evening media event (Tue 2026-03-10, 20:00 UTC) — the situation PLEX is about.
TUE_EVE = datetime(2026, 3, 10, 20, 0, tzinfo=UTC).timestamp()
# A weekend-morning presence event (Sat 2026-03-14, 08:00 UTC) — shares no token with PLEX.
SAT_MORN = datetime(2026, 3, 14, 8, 0, tzinfo=UTC).timestamp()


def make_recall(schemas):
    """The production closure shape (mirrors scripts/run.py): Event → firm GIST lines."""
    def _recall(event: Event):
        toks = event_tokens(event)
        if not toks:
            return []
        dt = datetime.fromtimestamp(event.ts, UTC)
        return recall(schemas, daytype=daytype_of(dt.date().isoformat()),
                      daypart=daypart_of(dt.hour * 60 + dt.minute), tokens=toks)
    return _recall


class RecallQueryTests(unittest.TestCase):
    def test_relevant_firm_line_is_recalled(self) -> None:
        lines = recall([PLEX], daytype="wd", daypart="eve", tokens=("media", "plex", "film"))
        self.assertEqual(lines, [line_text(PLEX)])
        self.assertIn(SENTINEL, lines[0])

    def test_no_token_overlap_recalls_nothing(self) -> None:
        # a different situation (a bedroom presence) shares no token → honest empty, not noise
        self.assertEqual(recall([PLEX], daytype="wd", daypart="eve", tokens=("home", "bedroom")), [])

    def test_tentative_line_below_the_floor_never_recalls(self) -> None:
        faint = Schema(kind="obs", daytype="wd", daypart="eve", tokens=("media", "plex"),
                       beta=Beta(a_q=1000, b_q=0))    # firmness 0 < GIST_NMIN
        self.assertEqual(recall([faint], daytype="wd", daypart="eve", tokens=("media", "plex")), [])

    def test_deterministic_and_capped(self) -> None:
        more = [PLEX,
                Schema(kind="rule", daytype="wd", daypart="eve", tokens=("media", "plex", "film"),
                       beta=Beta(a_q=16000, b_q=0)),
                Schema(kind="rule", daytype="wd", daypart="mid", tokens=("media", "plex"),
                       beta=Beta(a_q=8000, b_q=0))]
        a = recall(more, daytype="wd", daypart="eve", tokens=("media", "plex"), k=2)
        b = recall(list(reversed(more)), daytype="wd", daypart="eve", tokens=("media", "plex"), k=2)
        self.assertEqual(a, b)              # order-independent (the tie-break is total)
        self.assertEqual(len(a), 2)         # capped at k


# --------------------------------------------------------------------------- #
# The cortex injection — a fake LLM that BRANCHES on whether the recall reached the prompt.
# --------------------------------------------------------------------------- #
class _BranchingLLM:
    """Decides by reading ctx['recalled'] — the real injection path. If the broker is broken,
    the recalled line never arrives and the branch never taken."""
    async def propose(self, *, system, context, tools) -> Proposal:
        recalled = " ".join(context.get("recalled", []))
        if SENTINEL in recalled:
            return Proposal(tool_call=ToolCall(name="suggest_resume", arguments={}))
        return Proposal(say="What would you like to do?")


class _Sup:
    CATALOG = [{"type": "function",
                "function": {"name": "suggest_resume", "parameters": {"type": "object", "properties": {}}}}]

    def __init__(self):
        self.called = []

    def tool_catalog(self):
        return self.CATALOG

    async def call_function(self, fn, **args):
        self.called.append((fn, args))


class _Remember:
    async def normal(self, topic, zone, when):
        return Expectation(rate=0.0, count=0.0, days=0.0, novel=True)   # always novel → always wakes


class CortexInjectionTests(unittest.IsolatedAsyncioTestCase):
    def _media_event(self, ts):
        return Event("media.activity", ts, {"app": "plex", "state": "playing", "kind": "film"})

    async def _decide(self, *, recall_fn):
        bus, sup = Bus(), _Sup()
        reason = Reason(bus, _BranchingLLM(), sup, _Remember(), recall=recall_fn)
        await reason.start()
        await reason.decide(self._media_event(TUE_EVE), await _Remember().normal(None, None, None))
        await bus.drain()
        await bus.aclose()
        return sup

    async def test_retrieval_changes_a_decision(self) -> None:
        # WITHOUT memory: no recall → the model falls back to asking.
        cold = await self._decide(recall_fn=None)
        self.assertEqual(cold.called, [])                      # nothing acted

        # WITH memory: the firm "weekday evenings → Plex" line is retrieved, injected, and
        # FLIPS the decision to a concrete suggestion. Same event, only memory differs.
        warm = await self._decide(recall_fn=make_recall([PLEX]))
        self.assertEqual(warm.called, [("suggest_resume", {})])

    async def test_recall_is_selective_not_a_constant(self) -> None:
        # An unrelated event (weekend-morning presence) recalls nothing, so the model still
        # asks — proving the flip above is the recalled line, not a recall that always fires.
        bus, sup = Bus(), _Sup()
        reason = Reason(bus, _BranchingLLM(), sup, _Remember(), recall=make_recall([PLEX]))
        await reason.start()
        off = Event("presence.arrived", SAT_MORN, {"zone": "bedroom"})
        await reason.decide(off, await _Remember().normal(None, None, None))
        await bus.drain()
        await bus.aclose()
        self.assertEqual(sup.called, [])                       # no relevant memory → no action

    async def test_recall_fault_never_crashes_a_decision(self) -> None:
        def boom(event):
            raise RuntimeError("recall wedged")
        warm = await self._decide(recall_fn=boom)              # the cortex proceeds without memory
        self.assertEqual(warm.called, [])


class PrivacyInvariantTests(unittest.TestCase):
    def test_recalled_lines_are_plain_brief_text_no_embedding(self) -> None:
        # The Dream Journal stores no vectors; a recalled line is exactly render_brief text the
        # owner already sees on the 'What Homie Knows' page. No embedding exists to leak.
        lines = recall([PLEX], daytype="wd", daypart="eve", tokens=("media", "plex"))
        for ln in lines:
            self.assertIsInstance(ln, str)
            self.assertNotIn("[", ln)            # no list/array rendering — it's a sentence
            self.assertEqual(ln, line_text(PLEX))


if __name__ == "__main__":
    unittest.main()
