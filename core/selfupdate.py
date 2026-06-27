"""Self-update — pull the latest code, health-check it, and only then call it safe.

The update *channel* (Step 0 of the plain plan): the box runs a git checkout of this repo,
and updating is "pull, run the whole test suite, restart only if green". This module holds
the PURE decision logic — what a pull did, and whether the result is safe to apply — so it
is testable without a network or a daemon. `scripts/update.py` is the thin CLI that runs
the actual `git pull`, drives the health check via `core.status.run_test_suite`, and
(behind an explicit flag) restarts the service.

This is also the honest seed of Step 7 (the nightly self-upgrade): same pull -> health-check
-> restart, with automatic rollback on a failed check. Nothing here grants new authority or
touches devices; it only decides whether new *code* is safe to run.
"""
from __future__ import annotations


def parse_pull(returncode: int, stdout: str, stderr: str, before: str, after: str) -> dict:
    """Summarize a `git pull` from its exit code and the before/after commit hashes.
    Returns {ok, changed, summary} — pure, no I/O."""
    out = (stdout or "") + (stderr or "")
    if returncode != 0:
        last = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "git pull failed")
        return {"ok": False, "changed": False, "summary": last.strip()}
    if before == after:
        return {"ok": True, "changed": False, "summary": "already up to date"}
    return {"ok": True, "changed": True, "summary": f"updated {before[:7]} → {after[:7]}"}


def decide(pull: dict, tests: dict) -> tuple[bool, str]:
    """Given the pull result and a health-check result (the dict shape returned by
    `core.status.run_test_suite`), decide whether it is safe to restart onto the new code.
    Conservative by construction: anything uncertain is 'not safe'."""
    if not pull.get("ok"):
        return False, f"pull failed — {pull.get('summary')}. Nothing changed; the daemon is untouched."
    if not pull.get("changed"):
        return True, "already up to date — nothing to apply, no restart needed."
    if not tests.get("ran"):
        return False, "could NOT run the health check (tests did not run) — not safe to restart."
    if tests.get("ok"):
        return True, f"healthy — {tests.get('count')} checks passed. Safe to restart onto the new code."
    return False, (f"health check FAILED — {tests.get('count')} checks ran and some did not pass. "
                   "NOT safe to restart; roll back with: git reset --hard HEAD@{1}")


def format_report(pull: dict, tests: dict, safe: bool, message: str, *, restarted: bool = False) -> str:
    """A plain, SSH-friendly summary of an update attempt."""
    mark = "✅" if safe else "⛔"
    lines = ["Homie update", f"  pull:   {pull.get('summary')}"]
    if tests.get("ran"):
        verdict = f"{tests.get('count')} passed" if tests.get("ok") else f"{tests.get('count')} ran, some FAILED"
        lines.append(f"  health: {verdict} (in {tests.get('duration')}s)")
    elif pull.get("changed"):
        lines.append("  health: not run")
    lines.append(f"  {mark} {message}")
    if restarted:
        lines.append("  ↻ restarted homie.service onto the new code.")
    elif safe and pull.get("changed"):
        lines.append("  → to apply: sudo systemctl restart homie   (or re-run with --restart)")
    return "\n".join(lines) + "\n"
