#!/usr/bin/env python3
"""Homie status page — write a snapshot, or serve it live.

  python3 scripts/status.py                  # write status.html (open it anytime)
  python3 scripts/status.py --tests          # ...and run the suite for a live pass/fail
  python3 scripts/status.py --serve           # live at http://localhost:8765 (auto-refresh)
  python3 scripts/status.py --serve --tests   # live, re-running the suite (cached ~20s)

Every load regathers from git + disk, so the page reflects the system *now*. The daemon
state directory is read from --state or $HOMIE_STATE; without it the runtime panel just
says so and the project status still renders.
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import status as S  # noqa: E402


def _state_dir(arg: str | None) -> Path | None:
    val = arg or os.environ.get("HOMIE_STATE")
    return Path(val) if val else None


def write_once(out: Path, state: Path | None, run_tests: bool) -> Path:
    facts = S.gather(state_dir=state, run_tests=run_tests)
    out.write_text(S.render_html(facts, live=False), "utf-8")
    return out


def serve(host: str, port: int, state: Path | None, run_tests: bool, refresh: int) -> None:
    cache: dict = {"tests": None, "at": 0.0}
    ttl = 20.0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def do_GET(self):
            if self.path not in ("/", "/index.html", "/status.html"):
                self.send_error(404)
                return
            now = datetime.now().timestamp()
            do_tests = run_tests
            if run_tests and cache["tests"] is not None and (now - cache["at"]) < ttl:
                do_tests = False  # reuse the recent run; don't re-run on every refresh
            facts = S.gather(state_dir=state, run_tests=do_tests)
            if run_tests:
                if do_tests:
                    cache["tests"], cache["at"] = facts["tests"], now
                else:
                    facts["tests"] = cache["tests"]
            body = S.render_html(facts, live=True, refresh=refresh).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = HTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Homie status live at {url}  (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        httpd.server_close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Homie status page")
    ap.add_argument("--text", action="store_true", help="print the board to the terminal (great over SSH)")
    ap.add_argument("--no-color", action="store_true", help="plain text, no ANSI colour")
    ap.add_argument("--serve", action="store_true", help="serve live instead of writing a file")
    ap.add_argument("--tests", action="store_true", help="run the test suite for a live pass/fail")
    ap.add_argument("--out", default="status.html", help="output file (write mode)")
    ap.add_argument("--state", default=None, help="daemon state dir (default $HOMIE_STATE)")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--refresh", type=int, default=10, help="serve-mode auto-refresh seconds")
    args = ap.parse_args(argv)
    state = _state_dir(args.state)

    if args.serve:
        serve(args.host, args.port, state, args.tests, args.refresh)
        return 0
    if args.text:
        facts = S.gather(state_dir=state, run_tests=args.tests)
        color = not args.no_color and sys.stdout.isatty()
        sys.stdout.write(S.render_text(facts, color=color))
        return 0
    out = write_once(Path(args.out), state, args.tests).resolve()
    print(f"wrote {out}\nopen it in a browser: file://{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
