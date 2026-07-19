# Security Policy

## Reporting a vulnerability

If you have found something that could put a user's API keys or machine at
risk, **please report it without posting the details publicly.**

Open an issue titled "Security report" with no specifics — just say you have
one and how to reach you — and you'll get a reply to continue privately.

Useful things to include once we're in touch: what an attacker can do, the
steps to reproduce, and which version or commit you tested. A proof of concept
is welcome but not required.

Expect a first response within a week. You'll be credited when a fix ships,
unless you'd rather not be.

## What this project's threat model actually is

YuBen is a **local-first desktop app**. The backend is a localhost daemon, the
frontend is a local SPA, and there is no hosted service, no multi-tenancy and
no telemetry. That shapes what counts as a vulnerability here:

**In scope — these are real bugs, please report them:**

- An API key reaching anywhere it shouldn't: the browser, a log, a URL, an
  exported file, a subprocess that has no business seeing it, or a crash report.
- A web page you merely *visit* being able to reach the local backend — reading
  your research history, overwriting a stored key, spending your API quota, or
  triggering a subprocess. DNS rebinding and cross-site request forgery against
  `localhost` both count.
- Anything that gets arbitrary code, arguments or flags into a spawned CLI.
- A path that lets model output become trusted data. YuBen's central promise is
  that video IDs and numbers come from the deterministic pipeline and are
  re-verified — never from the LLM. A way around that is a security bug, not
  just a correctness one.
- Anything that writes outside the intended data directory.

**Out of scope:**

- Attacks that require the attacker to already have local code execution or an
  interactive shell as your user. At that point the app's secret store is not
  the weak link.
- The user pointing the app at their own machine, or misusing their own keys.
- Vulnerabilities in a model provider's CLI or API — report those upstream.
- Missing hardening with no demonstrated impact (a header, a version banner)
  unless you can show what it actually enables.

## Handling your own keys

YuBen stores provider keys in your OS keychain via `keyring`, falling back to a
`0600` file under `backend/.yuben/` when no keychain is available. Neither
location is in the repository, and the store is write-only toward the UI — the
frontend can set or test a key, never read one back.

If you think a key of yours has been exposed, rotate it at the provider first,
then investigate. Rotation is cheap; a leaked key is not.
