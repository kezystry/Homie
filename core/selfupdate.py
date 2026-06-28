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


# Charter 8a authority-freeze: a self-upgrade may change behaviour but NEVER widen Homie's own
# authority. Any changed file whose path hints at the capability gate, a device/zone/egress
# allowlist, the desktop safe-verb set, or trust rungs is held for the owner's explicit yes —
# EVEN IF the whole suite is green. Conservative substring match: over-flagging only ever asks.
_AUTHORITY_HINTS = ("capability", "act_map", "cameras.toml", "egress", "allowlist",
                    "never_touch", "trust", "core/desktop.py", "consent.py", "core/schema.py")


def authority_touched(changed_files) -> list[str]:
    """The subset of changed files that touch Homie's authority — these block an auto-upgrade."""
    return sorted({f for f in (changed_files or []) if any(h in f.lower() for h in _AUTHORITY_HINTS)})


def decide(pull: dict, tests: dict, changed_files=()) -> tuple[bool, str]:
    """Given the pull result, a health-check result (the dict shape from
    `core.status.run_test_suite`), and the changed file list, decide whether it is safe to
    auto-restart onto the new code. Conservative by construction: anything uncertain is 'not
    safe', and an authority-touching diff is held for the owner even when green (Charter 8a)."""
    if not pull.get("ok"):
        return False, f"pull failed — {pull.get('summary')}. Nothing changed; the daemon is untouched."
    if not pull.get("changed"):
        return True, "already up to date — nothing to apply, no restart needed."
    if not tests.get("ran"):
        return False, "could NOT run the health check (tests did not run) — not safe to restart."
    if not tests.get("ok"):
        return False, (f"health check FAILED — {tests.get('count')} checks ran and some did not pass. "
                       "NOT safe to restart; rolling back to the last good version.")
    touched = authority_touched(changed_files)
    if touched:
        return False, ("update is healthy BUT it changes what Homie is allowed to touch "
                       f"({', '.join(touched)}) — held for your explicit yes (Charter 8a). "
                       "Not auto-applied; nothing self-grants power.")
    return True, f"healthy — {tests.get('count')} checks passed. Safe to restart onto the new code."


def should_rollback(pull: dict, tests: dict, changed_files=()) -> bool:
    """True when code WAS pulled but is not safe to keep running — the auto-rollback trigger.
    (An authority-hold is NOT a rollback: the code is healthy, it just awaits the owner.)"""
    if not pull.get("changed"):
        return False
    if not tests.get("ran") or not tests.get("ok"):
        return True            # broken/unverifiable new code → return to last good
    return False               # green (or authority-held-but-green) → keep


def upgrade_outcome(pull: dict, tests: dict, changed_files=(), *, restarted: bool) -> str | None:
    """The one-word outcome the morning word speaks: 'applied' | 'rolledback' | 'held', or None
    when there is nothing worth a morning line (no change, or a failed pull). Pure — mirrors the
    verdict in `changelog_line`, but only for an update that actually changed code."""
    if not pull.get("changed"):
        return None
    if restarted:
        return "applied"
    if should_rollback(pull, tests, changed_files):
        return "rolledback"
    if authority_touched(changed_files):
        return "held"
    return None


def changelog_line(pull: dict, tests: dict, safe: bool, message: str, *, when: str) -> str:
    """One owner-readable line per nightly run (Charter 28e: no silent self-change)."""
    verdict = "applied" if safe else ("rolled-back" if should_rollback(pull, tests) else "held")
    checks = f"{tests.get('count')} checks" if tests.get("ran") else "no health check"
    return f"{when}  {verdict}: {pull.get('summary')} ({checks}) — {message}"


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
