# Release check

Run this once per OS before a release (reliability plan Phase 5, item 4). CI
already runs the backend tests and the frontend build on Ubuntu, Windows and
macOS. This covers what CI can't: real model keys, real agent CLIs, real YouTube
quota and a real browser.

## Budget

Each full run costs about 1,400 YouTube units; the free quota is 10,000 a day.
One OS needs three full runs plus one cancelled run, so roughly 5,000 units.
Two OSes fit in one day's quota; the third needs a second day or a second key.
The smoke steps spend no YouTube quota, only the model provider's tokens.

## Before you start

- [ ] Fresh clone of the release commit (not a working copy with old `.venv` or
      `node_modules`).
- [ ] CI is green for that commit on all three OSes.
- [ ] One API key (OpenAI, Anthropic or Gemini) and one installed agent CLI
      (Claude Code or Codex), both already signed in.

## Per OS

Tick each line for Windows, macOS and Linux. Write down the OS version, Python
and Node versions, the adapters and models used, and anything that went wrong.

### Install and start

- [ ] Start the way a new user would: double-click `start.cmd` (Windows) or
      `start.command` (macOS), or run `python3 yuben.py start` (Linux). The
      first run installs everything, builds the frontend and opens the browser.
- [ ] With something else already on port 8000, start again. YuBen says it
      picked another port, the page opens on it, and saving a key works (no 403).
- [ ] Ctrl-C (or closing the window) stops the server; nothing is left
      listening on the port.

### Smoke, no YouTube quota

- [ ] `python yuben.py smoke --adapter <api adapter> --model <model>` prints
      PASS.
- [ ] `python yuben.py smoke --adapter <cli adapter>` prints PASS. On Windows
      this is the real `.cmd` shim with a long prompt on stdin.

### Full runs in the app

- [ ] **API adapter, long-form:** a topic in English completes; the watch list,
      title analysis and game plan are filled in; every video link opens.
- [ ] **CLI adapter, Shorts:** completes the same way.
- [ ] **Non-English topic** (e.g. `как набрать подписчиков`) with either
      adapter: progress, keywords, titles and the report show Cyrillic correctly,
      with no `?` boxes or mojibake, and the run doesn't fail.
- [ ] **Cancel mid-run:** start a CLI run, cancel while it says "Analyzing".
      The run ends as cancelled within a few seconds, and the CLI is gone from
      Task Manager / Activity Monitor / `ps` (no orphaned `node` or agent
      process still using CPU).
- [ ] The finished runs appear in History and reopen without re-running.

## When something fails

Note the OS, adapter, model, the step, and the exact error text from the screen
and the terminal. Fix it before release; a failure here is one CI could not see,
so add a test for it where possible.
