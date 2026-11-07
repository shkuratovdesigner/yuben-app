#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, realpathSync } from 'node:fs';
import { chmod, mkdir, mkdtemp, open, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
const uvRelease = JSON.parse(await readFile(join(here, 'uv-release.json'), 'utf8'));
let child;
let interrupted = false;
const cancellation = new AbortController();

export function locations(env = process.env, platform = process.platform, home = homedir(), cwd = process.cwd()) {
  const base = platform === 'win32' ? join(env.LOCALAPPDATA || join(home, 'AppData', 'Local'), 'YuBen')
    : platform === 'darwin' ? join(home, 'Library', 'Application Support', 'YuBen')
      : join(env.XDG_DATA_HOME && isAbsolute(env.XDG_DATA_HOME) ? env.XDG_DATA_HOME : join(home, '.local', 'share'), 'yuben');
  const expand = p => p === '~' ? home : p.startsWith('~/') ? join(home, p.slice(2)) : resolve(cwd, p);
  return { home: env.YUBEN_HOME ? expand(env.YUBEN_HOME) : base,
    data: env.YUBEN_DATA_DIR ? expand(env.YUBEN_DATA_DIR) : join(env.YUBEN_HOME ? expand(env.YUBEN_HOME) : base, 'data') };
}

export function verifyDownload(buffer, expected) {
  if (createHash('sha256').update(buffer).digest('hex') !== expected) throw new Error('uv download checksum mismatch. Nothing was executed. Please retry.');
}

export function targetFor(platform = process.platform, arch = process.arch) {
  const target = uvRelease.targets[`${platform}-${arch}`];
  if (!target) throw new Error(`Unsupported platform ${platform}/${arch}. Use the source installation in the README.`);
  if (platform === 'linux' && !process.report.getReport().header.glibcVersionRuntime) throw new Error('The packaged launcher needs glibc Linux. On Alpine/musl, use the source installation.');
  return target;
}

function stopChild() {
  interrupted = true;
  cancellation.abort();
  if (!child?.pid) return;
  if (process.platform === 'win32') spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  else {
    try { process.kill(-child.pid, 'SIGTERM'); } catch { /* already exited */ }
  }
}

export function run(command, args, options = {}) {
  if (interrupted) throw new Error('Stopped.');
  return new Promise((accept, reject) => {
    const proc = spawn(command, args, { stdio: 'inherit', detached: process.platform !== 'win32', ...options });
    child = proc;
    proc.once('error', error => { child = undefined; reject(new Error(`Could not run ${command}: ${error.message}`)); });
    proc.once('close', (code, signal) => {
      child = undefined;
      if (code === 0 || interrupted) accept();
      else reject(new Error(`${command} exited with ${signal || code}. Check the message above and try again.`));
    });
  });
}

async function findUv(folder) {
  const name = process.platform === 'win32' ? 'uv.exe' : 'uv';
  if (existsSync(join(folder, name))) return join(folder, name);
  for (const item of await readdir(folder, { withFileTypes: true })) {
    if (item.isDirectory() && existsSync(join(folder, item.name, name))) return join(folder, item.name, name);
  }
  throw new Error('The uv release did not contain its executable.');
}

async function provisionUv(home) {
  const [asset, checksum] = targetFor();
  const bin = join(home, 'runtime', `uv-${uvRelease.version}-${process.platform}-${process.arch}`, process.platform === 'win32' ? 'uv.exe' : 'uv');
  if (existsSync(bin)) return bin;
  console.log('Downloading the Python installer (uv)…');
  const response = await fetch(`https://github.com/astral-sh/uv/releases/download/${uvRelease.version}/uv-${asset}`, { signal: AbortSignal.any([cancellation.signal, AbortSignal.timeout(120_000)]) });
  if (!response.ok) throw new Error(`Could not download uv: HTTP ${response.status}. Check your network and retry.`);
  const bytes = Buffer.from(await response.arrayBuffer());
  verifyDownload(bytes, checksum);
  const temp = await mkdtemp(join(home, 'uv-download-'));
  try {
    const archive = join(temp, asset.endsWith('.zip') ? 'uv.zip' : 'uv.tar.gz');
    await writeFile(archive, bytes);
    // macOS/Linux tar and Windows 10+ bsdtar support these official archives.
    await run('tar', ['-xf', archive, '-C', temp]);
    if (interrupted) throw new Error('Stopped.');
    const executable = await findUv(temp);
    await mkdir(dirname(bin), { recursive: true });
    await chmod(executable, 0o755);
    await rename(executable, bin);
  } finally { await rm(temp, { recursive: true, force: true }); }
  return bin;
}

async function provisionPython(home) {
  const requirements = join(root, 'app', 'backend', 'requirements-runtime.txt');
  const hash = createHash('sha256').update(await readFile(requirements)).digest('hex').slice(0, 16);
  const venv = join(home, 'runtime', `python-3.13-${process.platform}-${process.arch}-${hash}`);
  const python = join(venv, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const ready = join(venv, '.ready');
  if (existsSync(ready) && existsSync(python)) return python;
  const lock = join(home, 'setup.lock');
  let handle;
  try { handle = await open(lock, 'wx', 0o600); }
  catch (error) {
    if (error.code !== 'EEXIST') throw error;
    throw new Error(`Another YuBen setup may be running. Wait for it to finish and retry. If a previous setup crashed, stop it before removing ${lock}.`);
  }
  try {
    await handle.writeFile(JSON.stringify({ pid: process.pid, id: randomUUID() }));
    // Another invocation may have completed immediately before we acquired the lock.
    if (existsSync(ready) && existsSync(python)) return python;
    const uv = await provisionUv(home);
    const env = { ...process.env, UV_PYTHON_INSTALL_DIR: join(home, 'runtime', 'python'), UV_CACHE_DIR: join(home, 'cache'), UV_PYTHON_DOWNLOADS: 'automatic', UV_NO_CONFIG: '1' };
    console.log('Setting up Python 3.13 and YuBen dependencies (first run only)…');
    await run(uv, ['venv', '--python', '3.13', '--managed-python', '--clear', venv], { env });
    await run(uv, ['pip', 'sync', '--python', python, '--require-hashes', requirements], { env });
    if (interrupted) throw new Error('Stopped.');
    await writeFile(ready, hash);
    return python;
  } finally {
    await handle.close();
    await rm(lock, { force: true });
  }
}

export async function main(args = process.argv.slice(2)) {
  if (args.includes('--help') || args.includes('-h')) {
    console.log(`YuBen ${pkg.version}\n\nUsage: yuben-app [start] [--no-browser]\n       yuben-app --version\n\nFirst run installs a private Python runtime and dependencies, then opens YuBen.\nRun the same command again to reopen it. Ctrl+C stops the server.\nYUBEN_PORT: choose a port. YUBEN_DATA_DIR: reuse an existing data folder.\nYUBEN_HOME: override the private runtime and default data location.`);
    return;
  }
  if (args.length === 1 && ['--version', '-v'].includes(args[0])) { console.log(pkg.version); return; }
  const options = args[0] === 'start' ? args.slice(1) : args;
  if (options.some(arg => arg !== '--no-browser')) throw new Error('Unknown argument. Use --help for usage.');
  if (!existsSync(join(root, 'app', 'frontend', 'dist', 'index.html'))) throw new Error('This is a source checkout, not the distributable. Run npm run pack:app or use python yuben.py start.');
  targetFor();
  const paths = locations();
  await mkdir(paths.home, { recursive: true, mode: 0o700 });
  await mkdir(paths.data, { recursive: true, mode: 0o700 });
  console.log(`YuBen ${pkg.version}\nYour data: ${paths.data}`);
  const python = await provisionPython(paths.home);
  await run(python, [join(here, 'start.py'), ...options], {
    cwd: join(root, 'app', 'backend'),
    env: { ...process.env, YUBEN_DATA_DIR: paths.data, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
  });
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.on('SIGINT', stopChild);
  process.on('SIGTERM', stopChild);
  main().catch(error => {
    if (!interrupted) console.error(`\nyuben: ${error.message}`);
    process.exitCode = interrupted ? 130 : 1;
  });
}
