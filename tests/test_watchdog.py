"""Self-heal watchdog — pet systemd while healthy, withhold the ping when wedged.

Proves: it pings while healthy; it stops pinging once unhealthy past the grace window (so
systemd recycles a hung-but-running daemon); a raising health check counts as unhealthy; and
sd_notify is a harmless no-op with no NOTIFY_SOCKET.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.watchdog import Watchdog, sd_notify


async def _nosleep(_):
    return None


class _Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


class WatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_pings_while_healthy(self) -> None:
        sent: list = []
        wd = Watchdog(lambda: True, notify=lambda s: sent.append(s) or True,
                      sleep=_nosleep, now=_Clock(), max_ticks=3)
        await wd.run()
        self.assertEqual(sent[0], "READY=1")
        self.assertEqual(sent.count("WATCHDOG=1"), 3)

    async def test_withholds_ping_when_unhealthy_past_grace(self) -> None:
        clock = _Clock()
        sent: list = []
        async def tick_clock(_):                     # grace 30s; clock advances 20s per tick
            clock.t += 20.0
        wd = Watchdog(lambda: False, grace=30.0, notify=lambda s: sent.append(s) or True,
                      sleep=tick_clock, now=clock, max_ticks=4)
        await wd.run()
        pings = sent.count("WATCHDOG=1")
        self.assertGreaterEqual(pings, 1)            # within grace it still pets
        self.assertLessEqual(pings, 2)               # ...then stops → systemd recycles

    async def test_raising_health_is_unhealthy(self) -> None:
        sent: list = []
        def boom(): raise RuntimeError("status wedged")
        clock = _Clock()
        async def adv(_): clock.t += 100.0           # blow past grace immediately
        wd = Watchdog(boom, grace=30.0, notify=lambda s: sent.append(s) or True,
                      sleep=adv, now=clock, max_ticks=3)
        await wd.run()
        self.assertEqual(sent.count("WATCHDOG=1"), 1)   # one within grace, then withheld

    async def test_recovery_resumes_pinging(self) -> None:
        states = [True, False, True]
        sent: list = []
        wd = Watchdog(lambda: states.pop(0) if states else True,
                      notify=lambda s: sent.append(s) or True, sleep=_nosleep, now=_Clock(), max_ticks=3)
        await wd.run()
        self.assertEqual(sent.count("WATCHDOG=1"), 3)   # healthy, grace-covered blip, healthy


class SdNotifyTests(unittest.TestCase):
    def test_no_socket_is_a_noop(self) -> None:
        self.assertFalse(sd_notify("READY=1", sock_path=None))


if __name__ == "__main__":
    unittest.main()
