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
  test('sections line up with the logo and GitHub button, max 1400px', async ({ page }) => {
    for (const width of [1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/');
      const edges = await page.evaluate(() => {
        const box = (s: string) => document.querySelector(s)!.getBoundingClientRect();
        const left = box('.header-row .brand').left;
        const right = box('.github-header').right;
        const sides = ['.hero', '.closing', '.story-slot', '.shorts .section-copy', '.models .section-copy', '.faq-title', '.footer-brand'].map((s) => box(s).left);
        const ends = ['.hero', '.closing', '.story-stage .panel', '.shorts-track', '.model-grid', '.faq-list', '.footer-socials'].map((s) => box(s).right);
        return { left, right, sides, ends };
      });
      expect(edges.right - edges.left).toBeLessThanOrEqual(1400);
      for (const x of edges.sides) expect(Math.abs(x - edges.left)).toBeLessThan(1);
      for (const x of edges.ends) expect(Math.abs(x - edges.right)).toBeLessThan(1);
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
