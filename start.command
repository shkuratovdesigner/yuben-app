#!/bin/bash
# Double-click in Finder to install (first time) and start YuBen.
# Same as `python3 yuben.py start` from a terminal.
cd "$(dirname "$0")" || exit 1

# Finder starts this with a minimal PATH, so add the usual install folders.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "Python is not installed. Get Python 3.10+ from https://www.python.org/downloads/"
  echo "(or run: brew install python@3.13), then double-click start.command again."
  read -r -p "Press Return to close." _
  exit 1
fi

"$PY" yuben.py start
status=$?
if [ $status -ne 0 ] && [ $status -ne 130 ]; then
  read -r -p "YuBen stopped with an error. Press Return to close." _
fi
exit $status
