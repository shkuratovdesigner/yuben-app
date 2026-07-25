/**
 * `npm audit`, minus advisories reviewed and found not to apply to this app.
 *
 * Plain `npm audit --audit-level=high` has no way to say "we looked at this one
 * and it cannot affect us". The choice it leaves is a red CI forever or a
 * breaking downgrade, and a permanently red audit is the worse outcome: it stops
 * being read, so the *next* advisory — a real one — goes unnoticed too.
 *
 * So high/critical advisories still fail the build, except those listed in
 * ALLOWLIST below, each with a reason and a review date. The rules that keep
 * that from rotting into a blanket mute:
 *
 *   - An entry that no longer matches anything fails the build. Once a
 *     dependency is fixed the waiver has to be deleted, not left lying around.
 *   - An entry past its `reviewBy` fails the build. "Not applicable today" is
 *     not a claim that survives indefinitely without being re-checked.
 *   - If npm reports high/critical counts but no advisory could be parsed out,
 *     the build fails rather than passing. A silent no-op here would be
 *     indistinguishable from a clean audit, which is the one failure mode this
 *     script must not have.
 *
 * Rationale for each waiver belongs in SECURITY.md, not just in this file.
 */
import { execFileSync } from 'node:child_process'

/** Advisories reviewed against this app's actual usage and found unreachable. */
const ALLOWLIST = [
  {
    id: 'GHSA-qwww-vcr4-c8h2',
    package: 'react-router',
    reviewBy: '2026-10-31',
    reason:
      'CSRF bypass in the unstable RSC (React Server Components) APIs. The ' +
      'advisory states it only affects apps using those APIs; YuBen is a ' +
      'client-only SPA on BrowserRouter with no server rendering and no RSC ' +
      'entry point, so the vulnerable code path is not reachable. The fix is ' +
      'react-router 8.3.0, which for us means migrating off react-router-dom ' +
      '(v8 folded it into react-router) — tracked separately, not a patch bump.',
  },
]

/** Severities that fail the build, matching the old `--audit-level=high`. */
const BLOCKING = new Set(['high', 'critical'])

const GHSA_IN_URL = /(GHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4})/i

function runAudit() {
  // npm exits non-zero merely *because* it found vulnerabilities, so the exit
  // code says nothing about whether the run itself worked. Judge that by
  // whether the output parses instead.
  let stdout
  try {
    stdout = execFileSync('npm', ['audit', '--json'], {
      encoding: 'utf8',
      maxBuffer: 32 * 1024 * 1024,
    })
  } catch (err) {
    stdout = err.stdout ?? ''
  }

  try {
    return JSON.parse(stdout)
  } catch {
    console.error('Could not parse `npm audit --json` output:\n')
    console.error(stdout.slice(0, 2000) || '(no output)')
    process.exit(1)
  }
}

/**
 * Flatten the report into one entry per advisory.
 *
 * npm lists a package for every *path* to a vulnerability, so a transitive one
 * appears twice: once on the vulnerable package with the advisory attached, and
 * once on the dependent with `via: ['<name>']` pointing back. Only the former
 * carries an id, which makes the advisory — not the package rollup — the thing
 * to key decisions on.
 */
function advisoriesFrom(report) {
  const found = new Map()

  for (const vuln of Object.values(report.vulnerabilities ?? {})) {
    for (const via of vuln.via ?? []) {
      if (typeof via === 'string') continue
      if (!BLOCKING.has(via.severity)) continue

      const id = GHSA_IN_URL.exec(via.url ?? '')?.[1] ?? via.url ?? String(via.source)
      if (!found.has(id)) {
        found.set(id, {
          id,
          package: via.name,
          title: via.title,
          severity: via.severity,
          range: via.range,
          url: via.url,
        })
      }
    }
  }

  return [...found.values()]
}

function main() {
  const report = runAudit()
  const advisories = advisoriesFrom(report)

  const counts = report.metadata?.vulnerabilities ?? {}
  const blockingCount = (counts.high ?? 0) + (counts.critical ?? 0)
  if (blockingCount > 0 && advisories.length === 0) {
    console.error(
      `npm reports ${blockingCount} high/critical vulnerabilities but none ` +
        'could be parsed out of the report — the output shape has probably ' +
        'changed. Failing rather than reporting a clean audit.',
    )
    process.exit(1)
  }

  const waived = new Map(ALLOWLIST.map((entry) => [entry.id, entry]))
  const problems = []

  // Expired reviews first: a waiver nobody has re-checked is not a waiver.
  const today = new Date().toISOString().slice(0, 10)
  for (const entry of ALLOWLIST) {
    if (entry.reviewBy < today) {
      problems.push(
        `${entry.id} was waived until ${entry.reviewBy}, which has passed. ` +
          're-check whether it still cannot affect this app, then either ' +
          'extend the date with fresh reasoning or fix the dependency.',
      )
      waived.delete(entry.id)
    }
  }

  // Waivers for advisories that no longer show up: delete them, so the list
  // only ever describes the present.
  const present = new Set(advisories.map((a) => a.id))
  for (const entry of ALLOWLIST) {
    if (!present.has(entry.id)) {
      problems.push(
        `${entry.id} is allowlisted but no longer reported — the dependency ` +
          'looks fixed. Remove the entry from frontend/scripts/audit.mjs and ' +
          'from SECURITY.md.',
      )
    }
  }

  const unreviewed = advisories.filter((a) => !waived.has(a.id))
  for (const a of unreviewed) {
    problems.push(
      `${a.severity}: ${a.package} ${a.range ?? ''} — ${a.title}\n    ${a.url}`,
    )
  }

  for (const a of advisories.filter((a) => waived.has(a.id))) {
    console.log(`waived  ${a.id}  ${a.package}  (${a.title})`)
    console.log(`        ${waived.get(a.id).reason}\n`)
  }

  if (problems.length > 0) {
    console.error('\nnpm audit failed:\n')
    for (const problem of problems) console.error(`  - ${problem}`)
    console.error(
      '\nIf an advisory genuinely cannot affect this app, add it to ALLOWLIST ' +
        'in frontend/scripts/audit.mjs with a reason and a review date, and ' +
        'record it in SECURITY.md.',
    )
    process.exit(1)
  }

  const total = advisories.length
  console.log(
    total === 0
      ? 'npm audit: no high or critical advisories.'
      : `npm audit: ${total} high/critical advisory(ies), all reviewed and waived.`,
  )
}

main()
