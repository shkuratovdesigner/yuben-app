// Injects the server-rendered page into dist/index.html, then removes the SSR bundle.
import { readFile, writeFile, rm } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const { render } = await import(new URL('.ssr/entry-server.js', root));
const template = await readFile(new URL('dist/index.html', root), 'utf8');
if (!template.includes('<!--app-html-->')) throw new Error('Missing <!--app-html--> placeholder');
await writeFile(new URL('dist/index.html', root), template.replace('<!--app-html-->', render()));
await rm(new URL('.ssr', root), { recursive: true, force: true });
console.log('prerendered dist/index.html');
