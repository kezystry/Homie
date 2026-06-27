"""`homie` cockpit entrypoint — open the terminal cockpit by command.

    python3 -m cockpit                 # connect to the default socket
    python3 -m cockpit /path/to.sock   # or an explicit socket
    HOMIE_COCKPIT_SOCK=… python3 -m cockpit

The socket default mirrors scripts/run.py: $HOMIE_COCKPIT_SOCK, else
$HOMIE_STATE/cockpit.sock, else /var/lib/homie/cockpit.sock.
"""
import os
import sys
from pathlib import Path

from cockpit.client import CockpitClient
from cockpit.launcher import Launcher
from cockpit import tui


def default_socket() -> str:
    env = os.environ.get("HOMIE_COCKPIT_SOCK")
    if env:
        return env
    state = os.environ.get("HOMIE_STATE", "/var/lib/homie")
    return str(Path(state) / "cockpit.sock")


def main(argv: list[str]) -> int:
    sock = argv[1] if len(argv) > 1 else default_socket()
    tui.run(CockpitClient(sock), Launcher())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
