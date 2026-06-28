"""WatchLog — your media history, your taste, your recommendations (local, yours, wipeable).

The owner asked Homie to know what he watches and build a recommendation page — predictions
and a real understanding of his taste. This is that, and it stays his: it is his OWN activity
on his OWN machine, stored only here (never egressed, Charter law 2), always visible on the
"What Homie Knows" page, and forgettable in one tap (per-title or all). A one-tap
"screen-private" pause stops recording entirely (Charter 25 master controls).

Three layers, all stdlib:
  * `WatchLog`  — the durable, bounded, wipeable store of watch sessions (one JSON file).
  * analysis    — PURE functions over the sessions: top titles, taste by kind/time, the
                  binge/rewatch shape, a slot prediction. Same inputs → same output, tested.
  * `recommend` / `render_page` — the recommendation page: continue, tonight's prediction,
                  rewatch favorites, and plain-words understanding of his taste.
  * `WatchTracker` — a bus subscriber that turns the desktop adapter's `media.activity` events
                  into finished sessions and records them (honoring the private pause).

Honest limit: recommendations are built from HIS OWN history and rhythms — not an external
content database — so "brand-new titles like X" needs an opt-in metadata source (a future
add). What it does deeply: continue-watching, rewatch, "what you usually watch now", and an
honest read of his taste.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.gist import daypart_of, daytype_of
from core.tile import Event

log = logging.getLogger("homie.watchlog")

MEDIA = "media.activity"          # in: {app, state, kind?, title?} from the desktop adapter
PRIVATE = "media.private"         # in: {on: bool} — the one-tap "don't watch my screen" pause
SESSION_GAP_S = 1800.0            # a >30-min gap (or a title change) closes the current session
MIN_SESSION_S = 60.0             # ignore a blip shorter than a minute (channel-surfing)
KEEP = 4000                      # bounded history (oldest dropped) — never an infinite log


@dataclass(frozen=True)
class WatchSession:
    title: str
    kind: str          # 'film' | 'series' | 'unknown'
    app: str
    start: float
    end: float
    seconds: float
    daytype: str       # wd | we | aw
    daypart: str       # dawn..night

    @classmethod
    def of(cls, title, kind, app, start, end, *, tz=None) -> "WatchSession":
        dt = datetime.fromtimestamp(start, tz) if tz else datetime.fromtimestamp(start)
        return cls(title=title, kind=kind or "unknown", app=app, start=start, end=end,
                   seconds=max(0.0, end - start),
                   daytype=daytype_of(dt.date().isoformat()),
                   daypart=daypart_of(dt.hour * 60 + dt.minute))


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
class WatchLog:
    def __init__(self, path: Path | str, *, keep: int = KEEP) -> None:
        self.path = Path(path)
        self.keep = keep
        self._sessions: list[WatchSession] = self._load()

    def _load(self) -> list[WatchSession]:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            return [WatchSession(**r) for r in raw]
        except FileNotFoundError:
            return []
        except Exception:
            log.warning("watchlog: %s unreadable; starting empty", self.path)
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(s) for s in self._sessions], separators=(",", ":")), "utf-8")
        os.replace(tmp, self.path)

    def record(self, session: WatchSession) -> None:
        self._sessions.append(session)
        if len(self._sessions) > self.keep:
            self._sessions = self._sessions[-self.keep:]
        self._save()

    def sessions(self) -> list[WatchSession]:
        return list(self._sessions)

    def forget_title(self, title: str) -> int:
        """One-tap forget for a title — wipes every session of it, everywhere it's stored."""
        before = len(self._sessions)
        self._sessions = [s for s in self._sessions if s.title != title]
        self._save()
        return before - len(self._sessions)

    def clear(self) -> None:
        self._sessions = []
        self._save()


# --------------------------------------------------------------------------- #
# Analysis — PURE functions over a session list
# --------------------------------------------------------------------------- #
def top_titles(sessions: list[WatchSession], n: int = 5) -> list[tuple[str, int, float]]:
    """(title, times-watched, total-seconds), most-watched first — the rewatch favorites."""
    counts: Counter = Counter()
    secs: Counter = Counter()
    for s in sessions:
        counts[s.title] += 1
        secs[s.title] += s.seconds
    ranked = sorted(counts, key=lambda t: (-counts[t], -secs[t], t))
    return [(t, counts[t], secs[t]) for t in ranked[:n]]


def kind_breakdown(sessions: list[WatchSession]) -> dict[str, int]:
    c: Counter = Counter(s.kind for s in sessions)
    return dict(c)


def watch_slots(sessions: list[WatchSession]) -> Counter:
    """How often he watches in each (daytype, daypart) slot — the rhythm of his media life."""
    return Counter((s.daytype, s.daypart) for s in sessions)


def predict(sessions: list[WatchSession], now: float, *, tz=None) -> dict | None:
    """For the CURRENT slot, the kind he most often watches and the likeliest title, with an
    honest count behind it. None when there's no evidence for this slot yet."""
    dt = datetime.fromtimestamp(now, tz) if tz else datetime.fromtimestamp(now)
    slot = (daytype_of(dt.date().isoformat()), daypart_of(dt.hour * 60 + dt.minute))
    here = [s for s in sessions if (s.daytype, s.daypart) == slot]
    if not here:
        return None
    kind = Counter(s.kind for s in here).most_common(1)[0][0]
    title, hits = Counter(s.title for s in here).most_common(1)[0]
    return {"slot": slot, "kind": kind, "title": title, "hits": hits, "of": len(here)}


def understanding(sessions: list[WatchSession]) -> list[str]:
    """Plain-words read of his taste — only claims the evidence supports (honest by construction)."""
    if len(sessions) < 5:
        return []
    out: list[str] = []
    kinds = kind_breakdown(sessions)
    if kinds:
        fav = max(kinds, key=lambda k: kinds[k])
        if fav != "unknown":
            out.append(f"You watch {fav}s most ({kinds[fav]} of {len(sessions)} sessions).")
    slots = watch_slots(sessions)
    if slots:
        (dtp, dpt), hits = slots.most_common(1)[0]
        if hits >= 3:
            phrase = {"wd": "weekday", "we": "weekend", "aw": "away"}[dtp]
            out.append(f"Your usual viewing is {phrase} {dpt} ({hits} times).")
    favs = top_titles(sessions, 1)
    if favs and favs[0][1] >= 3:
        out.append(f"You keep coming back to “{favs[0][0]}” ({favs[0][1]}×) — a comfort rewatch.")
    return out


def recommend(sessions: list[WatchSession], now: float, *, tz=None, n: int = 5) -> list[dict]:
    """A ranked recommendation list from his own history: a slot-prediction, then rewatch
    favorites he hasn't seen most-recently. Each item carries WHY (honest provenance)."""
    recs: list[dict] = []
    p = predict(sessions, now, tz=tz)
    if p:
        recs.append({"title": p["title"], "why": f"you usually watch this {p['slot'][1]} ({p['hits']}×)",
                     "kind": p["kind"]})
    seen = {r["title"] for r in recs}
    for title, count, _ in top_titles(sessions, n * 2):
        if title in seen:
            continue
        recs.append({"title": title, "why": f"a favourite — watched {count}×",
                     "kind": next((s.kind for s in sessions if s.title == title), "unknown")})
        seen.add(title)
        if len(recs) >= n:
            break
    return recs[:n]


# --------------------------------------------------------------------------- #
# The recommendation page (plain text the cockpit / status page renders)
# --------------------------------------------------------------------------- #
def render_page(sessions: list[WatchSession], now: float, *, tz=None) -> list[str]:
    if not sessions:
        return ["Nothing watched yet — I'll learn your taste as you go."]
    lines = [f"Your viewing — {len(sessions)} sessions, {len({s.title for s in sessions})} titles."]
    p = predict(sessions, now, tz=tz)
    if p:
        lines.append(f"Tonight you'll probably want a {p['kind']} — maybe “{p['title']}”.")
    recs = recommend(sessions, now, tz=tz)
    if recs:
        lines.append("Picks for you:")
        lines += [f"  • {r['title']} — {r['why']}" for r in recs]
    insights = understanding(sessions)
    if insights:
        lines.append("What I've learned about your taste:")
        lines += [f"  • {i}" for i in insights]
    return lines


# --------------------------------------------------------------------------- #
# The tracker — media.activity events → finished sessions → the WatchLog
# --------------------------------------------------------------------------- #
class WatchTracker:
    """Assemble the desktop adapter's media events into watch sessions. A title change, a stop,
    or a >30-min gap closes the current session and records it (if it lasted a minute+). The
    one-tap `media.private` pause stops recording outright — nothing is stored while it's on."""

    def __init__(self, bus, log_store: WatchLog, *, tz: str | None = None) -> None:
        self.bus = bus
        self.store = log_store
        self._tz = ZoneInfo(tz) if tz else None
        self._open: dict | None = None       # {title, kind, app, start, last}
        self._private = False
        self._subs: list = []

    async def start(self) -> None:
        self._subs = [self.bus.subscribe(MEDIA, self._on_media, owner="watch"),
                      self.bus.subscribe(PRIVATE, self._on_private, owner="watch")]

    async def stop(self) -> None:
        self._finalize(self._open["last"] if self._open else 0.0)
        for s in self._subs:
            self.bus.unsubscribe(s)
        self._subs = []

    async def _on_private(self, event: Event) -> None:
        self._private = bool(event.payload.get("on", True))
        if self._private:
            self._finalize(self._open["last"] if self._open else 0.0)  # close + record what's done
            self._open = None
        log.info("watch: screen-private %s", "on" if self._private else "off")

    async def _on_media(self, event: Event) -> None:
        if self._private:
            return                                       # not watching while private
        p = event.payload or {}
        ts = float(event.ts)
        title = p.get("title")
        if not title:
            return
        if self._open and (self._open["title"] != title or ts - self._open["last"] > SESSION_GAP_S):
            self._finalize(self._open["last"])           # different title / long gap → close prior
            self._open = None
        if self._open is None:
            self._open = {"title": str(title), "kind": p.get("kind") or "unknown",
                          "app": str(p.get("app", "")), "start": ts, "last": ts}
        else:
            self._open["last"] = ts

    def _finalize(self, end: float) -> None:
        o = self._open
        if not o:
            return
        if end - o["start"] >= MIN_SESSION_S:
            self.store.record(WatchSession.of(o["title"], o["kind"], o["app"],
                                              o["start"], end, tz=self._tz))
        self._open = None
