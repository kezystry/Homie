"""The Layer 2 cockpit — a terminal control-plane over the bus.

A small stdlib-curses app, opened by the `homie` command (locally or over SSH),
that lets the resident watch the brain, chat with it, and launch apps/games. It
is a CLIENT of the daemon: it talks to the cockpit bridge over a local unix
socket (read + chat only) and shells out to gamescope/mpv for heavy pixels.

Modules:
  launcher  — the static app/game allowlist and a safe spawn (no arbitrary exec)
  client    — the line-protocol socket client to the cockpit bridge
  tui       — the curses three-pane UI (status / chat / launcher)
"""
