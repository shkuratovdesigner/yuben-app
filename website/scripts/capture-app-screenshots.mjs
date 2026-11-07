// Run from website/ while the app serves on 127.0.0.1:8077. Writes 2x PNGs to qa/app/ (ignored).
// Captures the three story screenshots from the real local app (light theme, 2x).
import { chromium } from '@playwright/test';
const RUN = 'r_24ef5e276c474cd19fbbf650e71aa886'; // I Built My Own AI App From Scratch (ranked)
const ANALYSIS_RUN = 'r_7226df8f96cd4c85829deb217e8745bf'; // Autonomous AI Agents (has title analysis)
const QUERY = 'I built my own AI app from scratch and this is how it works';
import { mkdirSync } from 'node:fs';
mkdirSync('qa/app', { recursive: true });
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2, colorScheme: 'light' });
await ctx.addInitScript(() => { try { localStorage.setItem('yuben-theme', 'light'); } catch {} });
const p = await ctx.newPage();
const clip = (x, y) => ({ x, y, width: 1200, height: 800 });

// 1. Composer with the report's real query typed and Titles Analytic on
await p.goto('http://127.0.0.1:8077/', { waitUntil: 'networkidle' });
await p.waitForTimeout(800);
await p.locator('textarea').first().fill(QUERY);
await p.getByText('Titles Analytic').click();
await p.mouse.move(5, 5);
await p.waitForTimeout(500);
const ht = await p.evaluate(() => Math.round(document.querySelector('h1').getBoundingClientRect().top));
await p.screenshot({ path: 'qa/app/shot-composer.png', clip: { x: 240, y: ht - 165, width: 960, height: 640 } });

// 2. Ranked results
await p.goto('http://127.0.0.1:8077/run/' + RUN, { waitUntil: 'networkidle' });
await p.waitForTimeout(1500);
const top = await p.evaluate(() => { const h = [...document.querySelectorAll('h2')].find(e => /Highest-Performed/.test(e.textContent)); return Math.round(h.getBoundingClientRect().top + scrollY); });
await p.evaluate((y) => scrollTo({ top: y - 48, behavior: 'instant' }), top);
await p.waitForTimeout(800);
await p.screenshot({ path: 'qa/app/shot-ranked.png', clip: clip(120, 0) });

// 3. Title analysis
await p.goto('http://127.0.0.1:8077/run/' + ANALYSIS_RUN, { waitUntil: 'networkidle' });
await p.waitForTimeout(1500);
const an = await p.evaluate(() => { const h = [...document.querySelectorAll('h2')].find(e => e.textContent.trim() === 'Analysis'); return Math.round(h.getBoundingClientRect().top + scrollY); });
await p.evaluate((y) => scrollTo({ top: y - 48, behavior: 'instant' }), an);
await p.waitForTimeout(800);
await p.screenshot({ path: 'qa/app/shot-analysis.png', clip: clip(120, 0) });
await b.close();
