import { expect, test } from '@playwright/test';

test.describe('without JavaScript @all', () => {
  test.use({ javaScriptEnabled: false });
  test('prerendered page shows all content', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Find your next');
    for (const text of ['Less reading', 'Your AI', 'A few quick answers', 'Made by Evgeny Shkuratov']) {
      await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
    }
    await expect(page.getByRole('heading', { name: /Your next video/ })).toBeVisible();
    await expect(page.locator('.hero .install-command')).toHaveText('npx yuben-app@latest');
    await expect(page.locator('.faq-item').first()).toHaveAttribute('open');
  });
});

test.describe('layout @all', () => {
  test('no horizontal page overflow', async ({ page }) => {
    await page.goto('/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  });
});

test.describe('container @desktop', () => {
  test('header, footer and sky cards share one frame; sections sit inside a 1600px container', async ({ page }) => {
    for (const width of [1024, 1440, 2000]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/');
      const m = await page.evaluate(() => {
        const box = (s: string) => document.querySelector(s)!.getBoundingClientRect();
        const frameL = ['.header-row .brand', '.hero', '.closing', '.footer-brand'].map((s) => box(s).left);
        const frameR = ['.github-header', '.hero', '.closing', '.footer-socials'].map((s) => box(s).right);
        const sides = ['.story-slot', '.shorts .section-copy', '.models .section-copy', '.faq-title'].map((s) => box(s).left);
        const ends = ['.story-stage .panel', '.shorts-track', '.model-grid', '.faq-list'].map((s) => box(s).right);
        return { vw: innerWidth, frameL, frameR, sides, ends, demo: [box('.demo').left, box('.hero').left] };
      });
      const frame = Math.max(20, m.vw * 0.035);
      const left = Math.max(48, m.vw * 0.08333, (m.vw - 1600) / 2);
      for (const x of m.frameL) expect(Math.abs(x - frame)).toBeLessThan(1);
      for (const x of m.frameR) expect(Math.abs(x - (m.vw - frame))).toBeLessThan(1);
      for (const x of m.sides) expect(Math.abs(x - left)).toBeLessThan(1);
      for (const x of m.ends) expect(Math.abs(x - (m.vw - left))).toBeLessThan(1);
      expect(m.demo[0] - m.demo[1]).toBeCloseTo(28, 0);
    }
  });

  test('copy button content is centred', async ({ page }) => {
    await page.goto('/');
    const gap = await page.evaluate(() => {
      const btn = document.querySelector('.hero .install-copy')!.getBoundingClientRect();
      const state = document.querySelector('.hero .install-state[data-on="true"]')!.getBoundingClientRect();
      return Math.abs((state.left - btn.left) - (btn.right - state.right));
    });
    expect(gap).toBeLessThan(1);
  });
});
