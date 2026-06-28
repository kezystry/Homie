#!/usr/bin/env python3
"""Update Homie: pull the latest code, health-check it, and report whether it's safe.

  python3 scripts/update.py              # pull + run the test suite; tells you if safe to restart
  python3 scripts/update.py --restart    # ...and restart homie.service if (and only if) it's healthy
  python3 scripts/update.py --check       # run the health check WITHOUT pulling (dry status)
  python3 scripts/update.py --restart --auto  # nightly self-upgrade: AUTO-rollback if unsafe

Conservative by design (Charter 28a/8a): a failed pull, a failed health check, or tests that
couldn't run all mean "not safe" and NO restart. With --auto, an unsafe-but-pulled update is
**automatically rolled back to the last good commit**, and any update that changes Homie's
AUTHORITY (the capability gate, an act-map/zone/egress allowlist, the desktop safe-verbs) is
HELD for the owner's explicit yes even when green. Every run appends one line to the changelog.
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


def _changed_files(before: str, after: str) -> list[str]:
    if not before or before == after:
        return []
    out = _git("diff", "--name-only", f"{before}..{after}").stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _append_changelog(line: str) -> None:
    try:
        path = ROOT / "update-changelog.txt"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # the changelog is a courtesy, never fatal to the upgrade


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Pull + health-check Homie")
    ap.add_argument("--restart", action="store_true", help="restart homie.service if the update is healthy")
    ap.add_argument("--check", action="store_true", help="health-check the current code without pulling")
    ap.add_argument("--auto", action="store_true", help="nightly mode: auto-rollback to last-good if unsafe")
    ap.add_argument("--service", default="homie", help="systemd service to restart (default: homie)")
    ap.add_argument("--now", default="", help="timestamp for the changelog (deploy passes date)")
    args = ap.parse_args(argv)

    before = "" if args.check else _head()
    if args.check:
        pull, changed = {"ok": True, "changed": True, "summary": "no pull (--check)"}, []
    else:
        p = _git("pull", "--ff-only")
        after = _head()
        pull = selfupdate.parse_pull(p.returncode, p.stdout, p.stderr, before, after)
        changed = _changed_files(before, after)

    tests = status.run_test_suite(ROOT) if pull.get("changed") else {"ran": None}
    safe, message = selfupdate.decide(pull, tests, changed)

    # --auto (nightly): a pulled-but-unsafe update is rolled back to the last good commit, so the
    # box keeps running known-good code. An authority-held update is also reset (its change must
    # not take effect on the next restart without the owner's yes) — but flagged, not failed.
    if args.auto and not safe and not args.check and pull.get("changed") and before:
        rb = _git("reset", "--hard", before)
        message += "  ↩ rolled back to the last good version." if rb.returncode == 0 else \
                   f"  (rollback failed: {rb.stderr.strip()})"

    restarted = False
    if safe and args.restart and pull.get("changed"):
        r = subprocess.run(["systemctl", "restart", args.service], capture_output=True, text=True)
        if r.returncode == 0:
            restarted = True
        else:
            message += f"  (restart failed: {r.stderr.strip() or 'try with sudo'})"
            safe = False

    if pull.get("changed") and not args.check:
        _append_changelog(selfupdate.changelog_line(pull, tests, safe, message, when=args.now or "—"))
    sys.stdout.write(selfupdate.format_report(pull, tests, safe, message, restarted=restarted))
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
