// Injects the server-rendered page into dist/index.html, then removes the SSR bundle.
import { readFile, writeFile, rm } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const { render, structuredDataScript } = await import(new URL('.ssr/entry-server.js', root));
const template = await readFile(new URL('dist/index.html', root), 'utf8');
for (const mark of ['<!--app-html-->', '<!--structured-data-->']) {
  if (!template.includes(mark)) throw new Error(`Missing ${mark} placeholder`);
}
const jsonLd = structuredDataScript();
if (jsonLd.includes('<')) throw new Error('JSON-LD must not contain "<"');
const graph = JSON.parse(jsonLd)['@graph'];
if (!graph.some((n) => n['@type'] === 'FAQPage' && n.mainEntity.length > 0)) throw new Error('JSON-LD is missing the FAQ');
const html = template
  .replace('<!--structured-data-->', () => jsonLd)
  .replace('<!--app-html-->', () => render());
await writeFile(new URL('dist/index.html', root), html);
await rm(new URL('.ssr', root), { recursive: true, force: true });
console.log('prerendered dist/index.html');
