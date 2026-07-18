"""Open a visible terminal running a command, for interactive auth flows.

Sign-in is interactive by design — an OAuth round-trip through a browser — so no
app can complete it silently on the user's behalf. What an app *can* do is remove
the "go find a terminal, remember the command, type it" step, which is the part
that actually makes connecting a model feel hard.

Used only by ``POST /api/config/remedy``, which passes a command defined by an
adapter in this codebase (``adapters/base.remedy``) — never one supplied by the
caller. YuBen is local-first: this spawns a terminal on the same machine the user
launched the app from, and it is always a response to them clicking the button.

Returns ``(launched, message)`` rather than raising, so an unsupported desktop
degrades to "here's the command, run it yourself" instead of an error.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import List, Tuple

#: Linux terminals, most-common first. The first one present wins.
_LINUX_TERMINALS: List[Tuple[str, List[str]]] = [
    ("x-terminal-emulator", ["-e", "bash", "-lc"]),
    ("gnome-terminal", ["--", "bash", "-lc"]),
    ("konsole", ["-e", "bash", "-lc"]),
    ("xfce4-terminal", ["-e", "bash", "-lc"]),
    ("alacritty", ["-e", "bash", "-lc"]),
    ("kitty", ["bash", "-lc"]),
]

_MANUAL = "Run this in your terminal: {}"


def _applescript_literal(command: str) -> str:
    """Escape a command for embedding in an AppleScript string literal."""
    return command.replace("\\", "\\\\").replace('"', '\\"')


def launch_in_terminal(command: str) -> Tuple[bool, str]:
    """Open a terminal window running ``command``. Never raises."""
    command = (command or "").strip()
    if not command:
        return False, "No command to run."

    try:
        if sys.platform == "darwin":
            return _launch_macos(command)
        if sys.platform.startswith("win"):
            return _launch_windows(command)
        return _launch_linux(command)
    except Exception as exc:  # pragma: no cover - desktop-specific failures
        return False, "Couldn't open a terminal ({}). {}".format(exc, _MANUAL.format(command))


def _launch_macos(command: str) -> Tuple[bool, str]:
    """Open Terminal on ``command`` via AppleScript.

    Deliberately fire-and-forget. The FIRST time this runs, macOS puts up an
    Automation consent dialog ("… wants to control Terminal") and osascript
    blocks until the user answers — which, waited on synchronously, hung the
    HTTP request for the full timeout and reported a bogus failure while the
    dialog was still on screen. So: spawn it, glance at the result, and let a
    pending consent dialog resolve in its own time.
    """
    # `do script` opens a new Terminal window and runs the command in it;
    # `activate` brings it to the front so the user actually sees the prompt.
    script = (
        'tell application "Terminal" to do script "{}"\n'
        'tell application "Terminal" to activate'.format(_applescript_literal(command))
    )
    proc = subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    try:
        # Long enough to catch an immediate hard failure, short enough that a
        # consent dialog doesn't stall the response.
        _out, err = proc.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        return True, (
            "Opening Terminal to run `{}`. If macOS asks whether to allow controlling "
            "Terminal, say yes — then finish signing in and test again.".format(command)
        )
    if proc.returncode == 0:
        return True, "Opened Terminal running `{}` — finish signing in there, then test again.".format(
            command
        )
    detail = (err or "").strip()
    return False, "Couldn't open Terminal{}. {}".format(
        " ({})".format(detail) if detail else "", _MANUAL.format(command)
    )


def _launch_windows(command: str) -> Tuple[bool, str]:
    # /k keeps the window open after the command finishes, so any final
    # instructions from the auth flow stay readable.
    subprocess.Popen(
        ["cmd", "/c", "start", "cmd", "/k", command],
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    return True, "Opened a terminal running `{}` — finish signing in there, then test again.".format(
        command
    )


def _launch_linux(command: str) -> Tuple[bool, str]:
    for binary, args in _LINUX_TERMINALS:
        path = shutil.which(binary)
        if not path:
            continue
        subprocess.Popen(
            [path, *args, command] if args[-1] == "-lc" or binary == "kitty" else [path, *args, command],
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        return True, "Opened {} running `{}` — finish signing in there, then test again.".format(
            binary, command
        )
    return False, "No terminal emulator found. {}".format(_MANUAL.format(command))
