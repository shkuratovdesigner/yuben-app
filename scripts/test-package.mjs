// Exercise the actual tarball from an unrelated directory with private runtime/data.
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, readdir, readFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { once } from 'node:events';
const root = resolve(import.meta.dirname, '..');
const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
const tarball = process.argv[2] || join(root, 'dist/npm', `${pkg.name}-${pkg.version}.tgz`);
const scratch = await mkdtemp(join(tmpdir(), 'yuben-package-'));
const unpack = spawnSync('tar', ['-xf', tarball, '-C', scratch], { encoding: 'utf8' });
assert.equal(unpack.status, 0, unpack.stderr);
const app = join(scratch, 'package');
assert.ok((await stat(join(app, 'app/frontend/dist/index.html'))).size > 0);
assert.ok((await stat(join(app, 'app/contracts/fixtures/research-result.longform.json'))).size > 0);
assert.ok(!(await readdir(join(app, 'app/backend'))).includes('.yuben'));
const env = { ...process.env, YUBEN_HOME: join(scratch, 'runtime'), YUBEN_DATA_DIR: join(scratch, 'saved-data'), YUBEN_FORCE_FILE_SECRET: '1', YUBEN_PORT: '18763' };
const delay = ms => new Promise(r => setTimeout(r, ms));
const base = `http://127.0.0.1:${env.YUBEN_PORT}`;
let initialHistory;
for (let pass = 0; pass < 2; pass++) {
  let log = '';
  const child = spawn(process.execPath, [join(app, 'launcher/cli.mjs'), '--no-browser'], { cwd: scratch, env, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.on('data', b => { log += b; process.stdout.write(b); });
  child.stderr.on('data', b => { log += b; process.stderr.write(b); });
  const closed = once(child, 'close');
  try {
    let healthy = false;
    for (let attempt = 0; attempt < 360; attempt++) {
      if (child.exitCode !== null) throw new Error(`Launcher exited ${child.exitCode}: ${log}`);
      try { healthy = (await fetch(`${base}/api/health`)).ok; } catch { /* still installing */ }
      if (healthy) break;
      await delay(1000);
    }
    assert.ok(healthy, 'server became healthy within six minutes');
    const html = await (await fetch(base)).text();
    assert.match(html, /<div id="root">/);
    const asset = html.match(/src="([^"]+\.js)"/)[1];
    assert.equal((await fetch(`${base}${asset}`)).status, 200);
    const history = await (await fetch(`${base}/api/history`)).json();
    assert.ok(Array.isArray(history) && history.length > 0, 'bundled example is available');
    if (!pass) initialHistory = history;
    else assert.deepEqual(history, initialHistory, 'history survives restart');
    assert.equal((await fetch(`${base}/api/missing`)).status, 404);
    assert.ok((await stat(join(env.YUBEN_DATA_DIR, 'yuben.db'))).size > 0);
    if (pass) assert.ok(!log.includes('Setting up Python'), 'second run reuses runtime');
  } finally {
    if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F']);
    else child.kill('SIGTERM');
    await Promise.race([closed, delay(15000).then(() => { throw new Error('Launcher failed to stop'); })]);
  }
  await delay(500);
  let alive = false;
  try { alive = (await fetch(`${base}/api/health`)).ok; } catch { /* stopped */ }
  assert.equal(alive, false, 'shutdown leaves no server behind');
}
console.log(`Package first-run, repeat-run, static assets, history and shutdown passed. Scratch: ${scratch}`);
