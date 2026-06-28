"""Self-heal watchdog — prove liveness to systemd so a HUNG (not just crashed) daemon recovers.

`Restart=always` only catches a process that *exits*. A daemon wedged in a deadlock or a stuck
loop is still "running" and would never recover. systemd's `WatchdogSec` fixes that: the daemon
must periodically send `WATCHDOG=1`; if it goes quiet past the deadline, systemd kills and
restarts it. This is that heartbeat, stdlib-only (`sd_notify` over a unix datagram — no
python-systemd dependency), plus the discipline that it stops petting the dog when the daemon
is unhealthy past a grace window, so "running but broken" also gets recycled (Charter 27a).

No NOTIFY_SOCKET (dev, tests, not-under-systemd) → every call is a harmless no-op.
"""
from __future__ import annotations

import logging
import os
import socket
import time

log = logging.getLogger("homie.watchdog")


def sd_notify(state: str, *, sock_path: str | None = None) -> bool:
    """Send one `sd_notify` datagram (e.g. "READY=1", "WATCHDOG=1"). Returns False when there is
    no NOTIFY_SOCKET — i.e. not running under a systemd watchdog — which is a silent no-op."""
    path = sock_path or os.environ.get("NOTIFY_SOCKET")
    if not path:
        return False
    addr = "\0" + path[1:] if path.startswith("@") else path   # abstract-namespace sockets
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(state.encode("utf-8"))
        return True
    except OSError as ex:
        log.warning("watchdog: sd_notify failed (%r)", ex)
        return False


class Watchdog:
    """Ping `WATCHDOG=1` on an interval — but only while `health()` is good. If the daemon is
    unhealthy for longer than `grace`, the pings STOP, and systemd's `WatchdogSec` recycles the
    process. `health`/`notify`/`sleep`/`now` are injectable so the loop is fully unit-testable."""

    def __init__(self, health, *, interval: float = 10.0, grace: float = 60.0,
                 notify=sd_notify, sleep=None, now=time.monotonic, max_ticks: int | None = None) -> None:
        self.health = health
        self.interval = interval
        self.grace = grace
        self._notify = notify
        self._sleep = sleep
        self._now = now
        self._max_ticks = max_ticks
        self.pings = 0          # telemetry / tests

    def _safe_health(self) -> bool:
        try:
            return bool(self.health())
        except Exception:
            log.exception("watchdog: health() raised; treating as unhealthy")
            return False

    async def run(self) -> None:
        import asyncio
        sleep = self._sleep or asyncio.sleep
        self._notify("READY=1")
        unhealthy_since: float | None = None
        ticks = 0
        while True:
            ok = self._safe_health()
            t = self._now()
            if ok:
                unhealthy_since = None
                self._notify("WATCHDOG=1")
                self.pings += 1
            else:
                if unhealthy_since is None:
                    unhealthy_since = t
                if t - unhealthy_since < self.grace:
                    self._notify("WATCHDOG=1")        # within grace — give it a chance to recover
                    self.pings += 1
                else:
                    log.error("watchdog: unhealthy for >%.0fs — withholding the ping; systemd will recycle", self.grace)
            ticks += 1
            if self._max_ticks is not None and ticks >= self._max_ticks:
                return
            await sleep(self.interval)
