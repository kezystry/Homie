#!/usr/bin/env python3
"""Update Homie: pull the latest code, health-check it, and report whether it's safe.

  python3 scripts/update.py              # pull + run the test suite; tells you if safe to restart
  python3 scripts/update.py --restart    # ...and restart homie.service if (and only if) it's healthy
  python3 scripts/update.py --check       # run the health check WITHOUT pulling (dry status)

Conservative by design: a failed pull, a failed health check, or tests that couldn't run all
mean "not safe" and NO restart happens. Roll back any bad update with:
  sudo git -C /opt/homie reset --hard HEAD@{1} && sudo systemctl restart homie
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import selfupdate, status  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=120)


def _head() -> str:
    return _git("rev-parse", "HEAD").stdout.strip()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Pull + health-check Homie")
    ap.add_argument("--restart", action="store_true", help="restart homie.service if the update is healthy")
    ap.add_argument("--check", action="store_true", help="health-check the current code without pulling")
    ap.add_argument("--service", default="homie", help="systemd service to restart (default: homie)")
    args = ap.parse_args(argv)

    if args.check:
        pull = {"ok": True, "changed": True, "summary": "no pull (--check)"}
    else:
        before = _head()
        p = _git("pull", "--ff-only")
        pull = selfupdate.parse_pull(p.returncode, p.stdout, p.stderr, before, _head())

    tests = status.run_test_suite(ROOT) if pull.get("changed") else {"ran": None}
    safe, message = selfupdate.decide(pull, tests)

    restarted = False
    if safe and args.restart and pull.get("changed"):
        r = subprocess.run(["systemctl", "restart", args.service], capture_output=True, text=True)
        if r.returncode == 0:
            restarted = True
        else:
            message += f"  (restart failed: {r.stderr.strip() or 'try with sudo'})"
            safe = False

    sys.stdout.write(selfupdate.format_report(pull, tests, safe, message, restarted=restarted))
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
