// Explicit allowlist: never ship a checkout's keys, history, caches or .env.
import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
const root = resolve(import.meta.dirname, '..');
const out = join(root, 'dist/npm');
await rm(out, { recursive: true, force: true });
await mkdir(join(out, 'app'), { recursive: true });
const copy = async (from, to = from) => {
  await mkdir(resolve(out, to, '..'), { recursive: true });
  await cp(join(root, from), join(out, to), { recursive: true, filter: src => !src.includes('__pycache__') && !src.endsWith('.pyc') });
};
for (const name of ['__init__.py', 'config.py', 'youtube_api.py', 'transcript.py', 'longform_research.py', 'shorts_research.py', 'yuben.py']) await copy(name, `app/${name}`);
for (const name of ['backend/app', 'backend/requirements-runtime.txt', 'contracts/python', 'contracts/schemas', 'contracts/fixtures', 'contracts/__init__.py', 'frontend/dist']) await copy(name, `app/${name}`);
await copy('launcher');
// Test sources are repository-only.
for (const name of await readdir(join(out, 'launcher'))) if (name.endsWith('.test.mjs')) await rm(join(out, 'launcher', name));
for (const name of ['LICENSE', 'README.md']) await copy(name);
const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
delete pkg.scripts;
await writeFile(join(out, 'package.json'), JSON.stringify(pkg, null, 2) + '\n');
console.log(`Packaged YuBen ${pkg.version} at ${out}`);
