"""Status — a live, self-contained status page derived from the REAL system.

This is not a hand-maintained doc: every fact is gathered fresh from disk and git at
render time — the milestone board (parsed from `docs/PROGRESS.md`), the branch and recent
commits, an optional live test run, and whatever the running/last-run daemon left in its
state directory (the event log's size and last activity, and the lessons tiles have
actually learned). Open it any time and it shows where Homie is *now*.

Pure stdlib, no daemon import: `core/status.py` gathers + renders; `scripts/status.py` is
the CLI that writes a file or serves it live. Kept here (not in scripts/) so it is
importable and testable like the rest of the core.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _beliefs_from_state(state: Path) -> list[str]:
    """Rebuild the pattern of life from the durability log (the production bootstrap path)
    and render the plain-language 'What Homie knows' lines. Best-effort and fully guarded —
    a missing/odd state never breaks the status page."""
    try:
        from core.bus import Bus
        from core.journal import what_homie_knows
        from core.remember import Remember
        log_path = state / "events.jsonl"
        if not any(state.glob("events*.jsonl")) and not (state / "events.snapshot.json").exists():
            return []
        bus = Bus(log_path=log_path)
        remember = Remember()
        remember.bootstrap(bus)
        rows = remember.beliefs(time.time())
        return what_homie_knows(rows) if rows else []
    except Exception:
        return []

# status word -> (emoji, css class) so the page and the parser agree on one vocabulary.
_STATUS = {
    "shipped": ("✅", "ok"),
    "building": ("🔄", "wip"),
    "planned": ("⏳", "plan"),
    "blocked": ("⏸", "blocked"),
}
_ICON_TO_WORD = {emoji: word for word, (emoji, _cls) in _STATUS.items()}


@dataclass(frozen=True)
class Milestone:
    id: str
    status: str  # one of _STATUS keys
    text: str

    @property
    def icon(self) -> str:
        return _STATUS.get(self.status, ("•", "plan"))[0]

    @property
    def css(self) -> str:
        return _STATUS.get(self.status, ("•", "plan"))[1]


# --------------------------------------------------------------------------- #
# Gather — each source is best-effort and never raises out of gather()
# --------------------------------------------------------------------------- #
def parse_milestones(progress_md: str) -> list[Milestone]:
    """Parse the fenced 'At a glance' block of docs/PROGRESS.md into structured rows.
    Lines look like:  `M3   ✅ shipped   Wake telemetry → ...`."""
    out: list[Milestone] = []
    in_glance = in_fence = False
    for line in progress_md.splitlines():
        if line.startswith("## "):
            in_glance = line.strip().lower().startswith("## at a glance")
            continue
        if in_glance and line.strip().startswith("```"):
            if in_fence:  # closing fence ends the block
                break
            in_fence = True
            continue
        if not (in_glance and in_fence):
            continue
        parts = line.split(None, 3)  # id, icon, word, rest
        if len(parts) < 4 or not parts[0].startswith("M"):
            continue
        mid, icon, word, text = parts
        status = _ICON_TO_WORD.get(icon) or (word.lower() if word.lower() in _STATUS else "planned")
        out.append(Milestone(id=mid, status=status, text=text.strip()))
    return out


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo_root), *args],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def git_facts(repo_root: Path) -> dict:
    branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "(unknown)"
    log = _git(repo_root, "log", "--oneline", "-12")
    commits = []
    for line in log.splitlines():
        h, _, subject = line.partition(" ")
        if h:
            commits.append({"hash": h, "subject": subject})
    return {"branch": branch, "commits": commits}


def run_test_suite(repo_root: Path, *, timeout: float = 120.0) -> dict:
    """Run the unittest suite and parse the result. Returns a dict that never raises;
    `ran` is None if the run could not be performed."""
    started = datetime.now()
    try:
        proc = subprocess.run(
            ["python3", "-m", "unittest", "discover", "-s", "tests"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=timeout)
    except Exception as ex:
        return {"ran": None, "ok": False, "count": None, "error": repr(ex)}
    duration = (datetime.now() - started).total_seconds()
    out = (proc.stderr or "") + (proc.stdout or "")
    m = re.search(r"Ran (\d+) test", out)  # "Ran 271 tests in 1.7s"
    count = int(m.group(1)) if m else None
    return {
        "ran": True,
        "ok": proc.returncode == 0,
        "count": count,
        "duration": round(duration, 2),
        "tail": "\n".join(out.strip().splitlines()[-3:]),
    }


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as fh:
            return sum(1 for _ in fh)
    except Exception:
        return 0


def _last_event_payload(state: Path, topic: str) -> dict | None:
    """The payload of the most recent event on `topic` in the log (or None). A cheap
    substring prefilter keeps this from JSON-parsing every line of a long log."""
    found: dict | None = None
    for f in sorted(state.glob("events*.jsonl")):
        try:
            with f.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if topic not in line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("topic") == topic and isinstance(ev.get("payload"), dict):
                        found = ev["payload"]
        except OSError:
            continue
    return found


def runtime_facts(state_dir: Path | None) -> dict:
    """Best-effort facts from a daemon state directory: how much it has lived (event log)
    and what its tiles have actually learned. Absent/unreadable -> {'present': False}."""
    if state_dir is None:
        return {"present": False, "reason": "no state directory configured"}
    state = Path(state_dir)
    if not state.exists():
        return {"present": False, "reason": f"state dir not found: {state}"}

    facts: dict = {"present": True, "path": str(state)}

    # The event log: live tail + compacted segments + snapshot length, and last activity.
    lines, newest = 0, 0.0
    for f in list(state.glob("events*.jsonl")):
        lines += _count_lines(f)
        newest = max(newest, f.stat().st_mtime)
    snap = state / "events.snapshot.json"
    if snap.exists():
        try:
            lines += len(json.loads(snap.read_text("utf-8")))
        except Exception:
            pass
        newest = max(newest, snap.stat().st_mtime)
    facts["events"] = {
        "count": lines,
        "last_activity": (datetime.fromtimestamp(newest, tz=timezone.utc).isoformat()
                          if newest else None),
    }

    # Lessons learned: each tile's persisted data.json. Lighting's `suppressed` map is the
    # flagship — the hours it learned to stay dark in a room (the M4 lesson, made visible).
    lessons: list[dict] = []
    for data in sorted(state.glob("tiles/*/state/data.json")):
        tile = data.parent.parent.name
        try:
            blob = json.loads(data.read_text("utf-8"))
        except Exception:
            continue
        suppressed = blob.get("suppressed") or {}
        for room, hours in sorted(suppressed.items()):
            lessons.append({"tile": tile, "room": room, "hours": sorted(hours)})
    facts["lessons"] = lessons

    # What Homie KNOWS (the Dream Journal page): plain-language firm beliefs about the
    # household's routines, rebuilt from the log. Honest beliefs only (>= the evidence floor).
    facts["knows"] = _beliefs_from_state(state)

    # The recommendation page: your watch history → taste + predictions + picks (best-effort,
    # guarded — a missing/odd watch.json never breaks the status page).
    # Live "now playing" — the answer to "what am I watching right now?".
    now_path = state / "now.json"
    if now_path.exists():
        try:
            facts["now_watching"] = json.loads(now_path.read_text("utf-8"))
        except Exception:
            pass

    watch_path = state / "watch.json"
    if watch_path.exists():
        try:
            from core.watchlog import WatchLog, render_page
            facts["watch"] = render_page(WatchLog(watch_path).sessions(), datetime.now().timestamp())
        except Exception:
            pass   # a missing/odd watch.json never breaks the status page

    # Serving health (M6): the latest reason.served telemetry — how quick the brain was on
    # its last wake, the rolling p95, whether it met the SLO, and the GPU's warm state.
    served = _last_event_payload(state, "reason.served")
    if served:
        facts["serving"] = {
            "latency_ms": served.get("latency_ms"),
            "p95_ms": served.get("p95_ms"),
            "slo_met": served.get("slo_met"),
            "warm": served.get("warm"),
        }
    return facts


def gather(repo_root: Path | None = None, state_dir: Path | None = None, *,
           run_tests: bool = False) -> dict:
    repo_root = Path(repo_root) if repo_root else ROOT
    progress = repo_root / "docs" / "PROGRESS.md"
    milestones = parse_milestones(progress.read_text("utf-8")) if progress.exists() else []
    shipped = sum(1 for m in milestones if m.status == "shipped")
    return {
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "milestones": milestones,
        "shipped": shipped,
        "total": len(milestones),
        "git": git_facts(repo_root),
        "tests": run_test_suite(repo_root) if run_tests else {"ran": None, "skipped": True},
        "runtime": runtime_facts(state_dir),
    }


# --------------------------------------------------------------------------- #
# Render — one self-contained HTML page, no external assets
# --------------------------------------------------------------------------- #
def _e(s) -> str:
    return html.escape(str(s))


def render_html(facts: dict, *, live: bool = False, refresh: int = 10) -> str:
    ms: list[Milestone] = facts["milestones"]
    bar = ""
    if facts["total"]:
        pct = round(100 * facts["shipped"] / facts["total"])
        bar = f'<div class="bar"><div class="fill" style="width:{pct}%"></div></div>' \
              f'<p class="muted">{facts["shipped"]} of {facts["total"]} milestones shipped ({pct}%)</p>'

    rows = "\n".join(
        f'<tr class="{m.css}"><td class="mid">{_e(m.id)}</td>'
        f'<td class="st">{m.icon} {_e(m.status)}</td><td>{_e(m.text)}</td></tr>'
        for m in ms) or '<tr><td colspan="3" class="muted">no milestone board found</td></tr>'

    commits = "\n".join(
        f'<li><code>{_e(c["hash"])}</code> {_e(c["subject"])}</li>'
        for c in facts["git"]["commits"]) or '<li class="muted">no commits</li>'

    t = facts["tests"]
    if t.get("skipped"):
        tests_html = '<span class="muted">not run this load — pass <code>--tests</code> to run</span>'
    elif t.get("ran"):
        cls = "ok" if t["ok"] else "blocked"
        word = "passing" if t["ok"] else "FAILING"
        tests_html = (f'<span class="pill {cls}">{_e(t.get("count"))} {word}</span> '
                      f'<span class="muted">in {_e(t.get("duration"))}s</span>')
    else:
        tests_html = f'<span class="pill blocked">could not run</span> <span class="muted">{_e(t.get("error",""))}</span>'

    rt = facts["runtime"]
    if rt.get("present"):
        ev = rt.get("events", {})
        last = ev.get("last_activity") or "—"
        lessons = rt.get("lessons") or []
        if lessons:
            litems = "\n".join(
                f'<li>{_e(l["tile"])}: stays dark in the <b>{_e(l["room"])}</b> at '
                f'{_e(", ".join(_oclock(h) for h in l["hours"]))}</li>' for l in lessons)
            lessons_html = f"<ul class='lessons'>{litems}</ul>"
        else:
            lessons_html = '<p class="muted">no lessons learned yet</p>'
        sv = rt.get("serving")
        if sv:
            warm = "warm" if sv.get("warm") else "asleep"
            slo = "within target" if sv.get("slo_met") else "over target"
            serving_html = (
                f'<h3>Brain speed</h3><p>last answer <b>{_e(sv.get("latency_ms"))} ms</b> '
                f'({_e(slo)}) · p95 <span class="muted">{_e(sv.get("p95_ms"))} ms</span> · '
                f'GPU <span class="muted">{_e(warm)}</span></p>')
        else:
            serving_html = ""
        knows = rt.get("knows") or []
        if knows:
            kitems = "\n".join(f"<li>{_e(line)}</li>" for line in knows)
            knows_html = f"<h3>What Homie knows about you</h3><ul class='lessons'>{kitems}</ul>"
        else:
            knows_html = ""
        watch = rt.get("watch") or []
        if watch:
            witems = "\n".join(f"<li>{_e(line)}</li>" for line in watch)
            watch_html = f"<h3>Your viewing — picks &amp; taste</h3><ul class='lessons'>{witems}</ul>"
        else:
            watch_html = ""
        runtime_html = (
            f'<p><b>{_e(ev.get("count", 0))}</b> events logged · last activity '
            f'<span class="muted">{_e(last)}</span></p>'
            f'{serving_html}'
            f'{knows_html}'
            f'{watch_html}'
            f'<h3>What Homie has learned</h3>{lessons_html}'
            f'<p class="muted tiny">{_e(rt.get("path",""))}</p>')
    else:
        runtime_html = (f'<p class="muted">Daemon state not found — showing project status only.'
                        f'<br>{_e(rt.get("reason",""))}</p>')

    meta_refresh = f'<meta http-equiv="refresh" content="{refresh}">' if live else ""
    live_note = (f'<span class="pill wip">live · refreshing every {refresh}s</span>'
                 if live else '<span class="muted">snapshot — re-run to update</span>')

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{meta_refresh}
<title>Homie · status</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; background:#0f1117; color:#e6e6e6; font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:880px; margin:0 auto; padding:28px 20px 64px; }}
  header {{ display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; }}
  h1 {{ font-size:26px; margin:0; }} h2 {{ font-size:15px; letter-spacing:.08em; text-transform:uppercase; color:#8a93a6; margin:34px 0 12px; }}
  h3 {{ font-size:14px; color:#b7c0d6; margin:16px 0 6px; }}
  .muted {{ color:#8a93a6; }} .tiny {{ font-size:12px; }}
  code {{ background:#1b1f2a; padding:1px 5px; border-radius:4px; font-size:13px; }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:7px 8px; border-top:1px solid #1e2430; vertical-align:top; }}
  .mid {{ font-weight:700; white-space:nowrap; width:54px; }} .st {{ white-space:nowrap; width:118px; }}
  tr.ok .st {{ color:#5ad17f; }} tr.wip .st {{ color:#f0c149; }} tr.plan .st {{ color:#8a93a6; }} tr.blocked .st {{ color:#ff6b6b; }}
  .bar {{ height:8px; background:#1b1f2a; border-radius:6px; overflow:hidden; margin:14px 0 4px; }}
  .fill {{ height:100%; background:linear-gradient(90deg,#3a7bd5,#5ad17f); }}
  .pill {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }}
  .pill.ok {{ background:#173a26; color:#5ad17f; }} .pill.wip {{ background:#3a3417; color:#f0c149; }} .pill.blocked {{ background:#3a1717; color:#ff6b6b; }}
  ul {{ margin:6px 0; padding-left:20px; }} li {{ margin:3px 0; }}
  .lessons li {{ color:#cdd6e6; }}
  .cards {{ display:flex; gap:14px; flex-wrap:wrap; margin-top:10px; }}
  .card {{ flex:1 1 240px; background:#151926; border:1px solid #1e2430; border-radius:10px; padding:14px 16px; }}
  footer {{ margin-top:40px; color:#5b6images; }}
</style></head>
<body><div class="wrap">
  <header><h1>🏠 Homie</h1> {live_note}
    <span class="muted" style="margin-left:auto">generated {_e(facts["generated_at"])}</span></header>

  {bar}

  <div class="cards">
    <div class="card"><h3>Branch</h3><code>{_e(facts["git"]["branch"])}</code></div>
    <div class="card"><h3>Tests</h3>{tests_html}</div>
    <div class="card"><h3>Milestones</h3><b>{_e(facts["shipped"])}</b> / {_e(facts["total"])} shipped</div>
  </div>

  <h2>Milestone board</h2>
  <table><tbody>{rows}</tbody></table>

  <h2>Runtime</h2>
  {runtime_html}

  <h2>Recent commits</h2>
  <ul>{commits}</ul>

  <footer class="muted tiny">Generated by <code>scripts/status.py</code> from live git + disk state ·
    the source of truth is the test suite and <code>docs/MASTERPLAN.md</code>.</footer>
</div></body></html>"""


def _oclock(hour: int) -> str:
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12}{suffix}"


# --------------------------------------------------------------------------- #
# Render — a terminal board for SSH (no browser, no port-forward)
# --------------------------------------------------------------------------- #
_ANSI = {"ok": "32", "wip": "33", "plan": "90", "blocked": "31", "head": "1;36", "dim": "90"}


def render_text(facts: dict, *, color: bool = True, width: int = 64) -> str:
    """The same status as the HTML page, rendered for a terminal — what you see when you
    SSH in from your phone. ANSI-coloured unless `color=False`."""
    def c(s, key):
        return f"\033[{_ANSI[key]}m{s}\033[0m" if color and key in _ANSI else str(s)

    L: list[str] = []
    L.append(c("🏠 Homie · status", "head") + c(f"   {facts['generated_at']}", "dim"))

    shipped, total = facts["shipped"], facts["total"]
    if total:
        pct = round(100 * shipped / total)
        filled = round(width * shipped / total)
        bar = "█" * filled + "·" * (width - filled)
        L.append(f"  [{c(bar, 'ok')}] {shipped}/{total} shipped ({pct}%)")

    git, t = facts["git"], facts["tests"]
    if t.get("skipped"):
        tline = c("not run (pass --tests)", "dim")
    elif t.get("ran"):
        tline = c(f"{t.get('count')} passing" if t["ok"] else f"{t.get('count')} FAILING",
                  "ok" if t["ok"] else "blocked") + c(f" in {t.get('duration')}s", "dim")
    else:
        tline = c("could not run", "blocked")
    L.append(f"  branch {c(git['branch'], 'head')}   tests {tline}")

    L.append("")
    L.append(c("  MILESTONES", "dim"))
    for m in facts["milestones"]:
        L.append(f"  {m.id:<5} {c(f'{m.icon} {m.status:<8}', m.css)} {m.text}")

    rt = facts["runtime"]
    L.append("")
    L.append(c("  RUNTIME", "dim"))
    if rt.get("present"):
        ev = rt.get("events", {})
        L.append(f"  {ev.get('count', 0)} events · last {c(ev.get('last_activity') or '—', 'dim')}")
        sv = rt.get("serving")
        if sv:
            warm = "warm" if sv.get("warm") else "asleep"
            slo_key = "ok" if sv.get("slo_met") else "blocked"
            L.append(f"  brain {c(str(sv.get('latency_ms')) + 'ms', slo_key)} last · "
                     f"p95 {c(str(sv.get('p95_ms')) + 'ms', 'dim')} · GPU {c(warm, 'dim')}")
        lessons = rt.get("lessons") or []
        if lessons:
            L.append(c("  what Homie has learned:", "dim"))
            for l in lessons:
                hrs = ", ".join(_oclock(h) for h in l["hours"])
                L.append(f"    · {l['tile']}: dark in the {c(l['room'], 'ok')} at {hrs}")
        else:
            L.append(c("    (no lessons learned yet)", "dim"))
        now = rt.get("now_watching")
        if now:
            L.append(c(f"  ▶ now watching: {now.get('title')} ({now.get('app')})", "dim"))
        knows = rt.get("knows") or []
        if knows:
            L.append(c("  what Homie knows about you:", "dim"))
            for line in knows:
                L.append(f"    · {line}")
        watch = rt.get("watch") or []
        if watch:
            L.append(c("  your viewing — picks & taste:", "dim"))
            for line in watch:
                L.append(f"    {line}" if line.startswith("  ") else f"    · {line}")
    else:
        L.append(c(f"  daemon state not found — {rt.get('reason', '')}", "dim"))

    L.append("")
    L.append(c("  RECENT", "dim"))
    for cm in git["commits"][:6]:
        L.append(f"  {c(cm['hash'], 'wip')} {cm['subject']}")
    return "\n".join(L) + "\n"
