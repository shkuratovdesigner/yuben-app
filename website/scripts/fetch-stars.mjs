// Refreshes the cached GitHub star count at build time. Never fails the build:
// on any error the last known value in src/data/stars.json is kept.
import { readFile, writeFile } from 'node:fs/promises';

const file = new URL('../src/data/stars.json', import.meta.url);
const cached = JSON.parse(await readFile(file, 'utf8'));
try {
  const response = await fetch('https://api.github.com/repos/shkuratovdesigner/yuben-app', {
    headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'yuben-website-build' },
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`GitHub responded ${response.status}`);
  const { stargazers_count: count } = await response.json();
  if (!Number.isInteger(count)) throw new Error('No star count in response');
  await writeFile(file, `${JSON.stringify({ count, fetchedAt: new Date().toISOString().slice(0, 10) }, null, 2)}\n`);
  console.log(`stars: ${count}`);
} catch (error) {
  console.warn(`stars: kept cached ${cached.count} (${error.message})`);
}
