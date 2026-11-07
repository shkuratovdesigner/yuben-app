import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { locations, verifyDownload, targetFor, main } from './cli.mjs';

test('data is outside ephemeral npm caches on each supported OS', () => {
  assert.equal(locations({}, 'darwin', '/users/me').data, '/users/me/Library/Application Support/YuBen/data');
  assert.equal(locations({}, 'linux', '/users/me').data, '/users/me/.local/share/yuben/data');
  assert.equal(locations({ LOCALAPPDATA: '/local' }, 'win32', '/users/me').data, '/local/YuBen/data');
});
test('explicit data folder survives cwd change and home override', () => {
  assert.deepEqual(locations({ YUBEN_HOME: '/runtime', YUBEN_DATA_DIR: 'backend/.yuben' }, 'linux', '/users/me', '/repo'), { home: '/runtime', data: '/repo/backend/.yuben' });
  assert.equal(locations({ YUBEN_DATA_DIR: '~/old-data' }, 'linux', '/users/me').data, '/users/me/old-data');
  assert.equal(locations({ XDG_DATA_HOME: 'relative' }, 'linux', '/users/me').home, '/users/me/.local/share/yuben');
});
test('download corruption fails before extraction or execution', () => {
  const bytes = Buffer.from('official release');
  verifyDownload(bytes, createHash('sha256').update(bytes).digest('hex'));
  assert.throws(() => verifyDownload(Buffer.from('changed'), createHash('sha256').update(bytes).digest('hex')), /checksum mismatch/);
});
test('unsupported platforms fail with source-install guidance', () => {
  assert.throws(() => targetFor('freebsd', 'x64'), /source installation/);
  assert.throws(() => targetFor('darwin', 'ia32'), /Unsupported platform/);
});
test('bad arguments fail before creating or downloading anything', async () => {
  await assert.rejects(main(['--unknown']), /Unknown argument/);
});
