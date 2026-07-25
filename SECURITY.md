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

## Dependency advisories

CI fails on any high or critical advisory in the dependency tree. A handful are
genuinely unreachable in an app shaped like this one, and rather than leave the
audit permanently red — at which point nobody reads it and the *next* advisory
goes unnoticed — those are waived explicitly, each with a reason and a date by
which the reasoning gets re-checked. The list lives in
`frontend/scripts/audit.mjs`; a waiver that no longer matches anything, or one
past its review date, fails the build just like an unreviewed advisory.

Currently waived:

| Advisory | Package | Why it cannot affect YuBen | Review by |
|---|---|---|---|
| [GHSA-qwww-vcr4-c8h2](https://github.com/advisories/GHSA-qwww-vcr4-c8h2) | `react-router` | CSRF bypass in the **unstable RSC APIs**. The advisory states it only affects applications using those APIs. YuBen is a client-only SPA on `BrowserRouter` — no server rendering, no RSC entry point, no server actions — so the vulnerable path does not exist here. | 2026-10-31 |

The fix for that one is `react-router` 8.3.0, which is a major upgrade rather
than a patch: v8 folded `react-router-dom` into `react-router`, so it means
changing every router import, not bumping a version. Worth doing on its own
merits — just not as a security hotfix for something unreachable.

If you think a waived advisory *is* reachable here, that is exactly the kind of
report this policy wants — see the top of this file.

## Handling your own keys

YuBen stores provider keys in your OS keychain via `keyring`, falling back to a
`0600` file under `backend/.yuben/` when no keychain is available. Neither
location is in the repository, and the store is write-only toward the UI — the
frontend can set or test a key, never read one back.

If you think a key of yours has been exposed, rotate it at the provider first,
then investigate. Rotation is cheap; a leaked key is not.
