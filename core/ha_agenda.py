"""HA agenda source — the live calendar / to-do / weather feed for the morning briefing.

The Agenda's source mappers (`agenda.from_ha_calendar`, `from_ha_todo`, `weather_clause`)
were pure and already tested; this is the missing live half — the thing that actually ASKS
Home Assistant and puts the answer on the bus. It is a thin, fail-soft poller:

  * on `tick.hour` (and on `time.morning`, so the day opens fresh) it fetches today+horizon
    calendar events, the open to-do items, and the current weather,
  * normalizes them with the existing pure mappers, and publishes ONE `agenda.external`
    snapshot the Personal tile caches and folds into the briefing.

Decoupled on purpose: the tile never blocks on the network. It renders the most recent
cached snapshot (≤1h old), so a slow or down HA degrades to a slightly stale briefing, never
a hung morning. Every fetch is independently guarded — a flaky calendar never costs you the
weather, and a total HA outage just publishes an empty snapshot (an honest quiet day).

`query` is injected (an `HAQuery`): the real one wraps the HA WebSocket (`HAWsQuery`), a fake
one drives the tests. The source owns NO rendering and NO store — same discipline as the rest.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from core.tile import Event

log = logging.getLogger("homie.ha_agenda")

EXTERNAL = "agenda.external"   # out: {"events": [...], "todos": [...], "weather": {...}|None}
TICK_HOUR = "tick.hour"
TIME_MORNING = "time.morning"
DEFAULT_HORIZON_DAYS = 2       # look two days out so tomorrow-morning's first thing never surprises


class HAQuery(Protocol):
    """The read seam to Home Assistant. Three independent fetches; each returns the plain
    dict shape the agenda mappers already consume (see `core/agenda.py`)."""

    async def calendar_events(self, start: float, end: float) -> list[dict]: ...
    async def todos(self) -> list[dict]: ...
    async def weather(self) -> dict | None: ...


class HAAgendaSource:
    """Poll HA for calendar/to-do/weather and publish a normalized `agenda.external` snapshot.
    Wire in `build_daemon` only when a real HA query client exists; `start()` after the clock
    so its ticks are live. Holds the bus to publish and the query to fetch — nothing else."""

    def __init__(self, bus, query: HAQuery, *, horizon_days: int = DEFAULT_HORIZON_DAYS,
                 tz: str | None = None) -> None:
        self.bus = bus
        self.query = query
        self._horizon = max(1, int(horizon_days)) * 86400.0
        self._tz = ZoneInfo(tz) if tz else None
        self._subs: list = []

    async def start(self) -> None:
        self._subs = [
            self.bus.subscribe(TICK_HOUR, self._refresh, owner="ha_agenda"),
            self.bus.subscribe(TIME_MORNING, self._refresh, owner="ha_agenda"),
        ]

    async def stop(self) -> None:
        for s in self._subs:
            self.bus.unsubscribe(s)
        self._subs = []

    def _day_start(self, now: float) -> float:
        dt = datetime.fromtimestamp(now, self._tz) if self._tz else datetime.fromtimestamp(now)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    async def _refresh(self, event: Event) -> None:
        now = event.ts
        start = self._day_start(now)
        end = start + self._horizon
        events = await self._safe(self.query.calendar_events(start, end), "calendar", [])
        todos = await self._safe(self.query.todos(), "todos", [])
        weather = await self._safe(self.query.weather(), "weather", None)
        await self.bus.publish(Event(EXTERNAL, now,
                                     {"events": events, "todos": todos, "weather": weather},
                                     source="ha"))

    async def _safe(self, coro, what: str, default):
        """Await one fetch; on any failure log and substitute the default so a single flaky
        source never sinks the whole snapshot."""
        try:
            return await coro
        except Exception as ex:   # network / HA-side / shape error — degrade, never raise
            log.warning("ha_agenda: %s fetch failed (%r); using %r", what, ex, default)
            return default


class HAWsQuery:
    """The real `HAQuery`: calendar / to-do / weather over the HA WebSocket (`client.request`).

    Marked for live validation — the exact WS message types and the weather attribute names
    vary across HA versions, and headless tests can't reach a real hub. The unit tests drive a
    fake `HAQuery`; this is the production wiring, wrapped fail-soft by `HAAgendaSource`.

    `entities` lists which `calendar.*` / `todo.*` / `weather.*` to read (discoverable from
    `get_states`); empty lists simply yield nothing.
    """

    def __init__(self, client, *, calendars: list[str] | None = None,
                 todo_lists: list[str] | None = None, weather_entity: str | None = None) -> None:
        self.client = client
        self.calendars = calendars or []
        self.todo_lists = todo_lists or []
        self.weather_entity = weather_entity

    async def calendar_events(self, start: float, end: float) -> list[dict]:
        out: list[dict] = []
        s = datetime.fromtimestamp(start).isoformat()
        e = datetime.fromtimestamp(end).isoformat()
        for entity in self.calendars:
            res = await self.client.request({
                "type": "calendar/event/list", "entity_id": entity, "start": s, "end": e})
            for ev in (res or []):
                out.append(_calendar_event(entity, ev))
        return out

    async def todos(self) -> list[dict]:
        out: list[dict] = []
        for entity in self.todo_lists:
            res = await self.client.request({
                "type": "todo/item/list", "entity_id": entity})
            items = (res or {}).get("items", res) if isinstance(res, dict) else res
            for it in (items or []):
                if str(it.get("status", "needs_action")) != "completed":
                    out.append(_todo_item(entity, it))
        return out

    async def weather(self) -> dict | None:
        if not self.weather_entity:
            return None
        res = await self.client.request({"type": "get_states"})
        for st in (res or []):
            if st.get("entity_id") == self.weather_entity:
                return _weather_state(st)
        return None


# -- raw HA payload → the plain dict the agenda mappers expect ------------------ #
def _epoch(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None


def _calendar_event(entity: str, ev: dict) -> dict:
    start = ev.get("start") or {}
    end = ev.get("end") or {}
    # HA gives either {"dateTime": ...} (timed) or {"date": ...} (all-day)
    all_day = isinstance(start, dict) and "date" in start and "dateTime" not in start
    s = _epoch(start.get("dateTime") or start.get("date") if isinstance(start, dict) else start)
    e = _epoch(end.get("dateTime") or end.get("date") if isinstance(end, dict) else end)
    return {"start": s, "end": e, "all_day": all_day, "summary": ev.get("summary"),
            "location": ev.get("location"), "uid": ev.get("uid"), "entity": entity}


def _todo_item(entity: str, it: dict) -> dict:
    return {"summary": it.get("summary"), "due": _epoch(it.get("due")),
            "uid": it.get("uid"), "entity": entity}


def _weather_state(st: dict) -> dict:
    attrs = st.get("attributes") or {}
    return {"condition": st.get("state"),
            "high": attrs.get("temperature"), "low": attrs.get("templow")}
