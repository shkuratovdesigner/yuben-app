import { expect, test, type Page } from '@playwright/test';

const titles = ['Start with a question', 'Find the unexpected winners', 'See the idea behind the views'];

/** Pinned scroll geometry of the steps list: offset into the pinned range and its length. */
const geometry = (page: Page) => page.evaluate(() => {
  const r = document.querySelector('.story-steps')!.getBoundingClientRect();
  return { offset: -r.top, range: r.height - innerHeight };
});
/** Independent expectation: the pinned range split into three equal parts. */
const expectedStage = async (page: Page) => {
  const { offset, range } = await geometry(page);
  return Math.min(2, Math.max(0, Math.floor((offset / range) * 3)));
};
const activeCopy = (page: Page) => page.locator('.story-copy[data-active="true"] .feature-title').textContent();
/** Scrolls to a fraction of stage i's equal share of the pinned range. */
const scrollToStage = (page: Page, i: number, frac = 0.5) => page.evaluate(([i, frac]) => {
  const steps = document.querySelector('.story-steps') as HTMLElement;
  const top = steps.getBoundingClientRect().top + scrollY;
  const range = steps.offsetHeight - innerHeight;
  scrollTo({ top: top + (range * (i + frac)) / 3, behavior: 'instant' });
}, [i, frac]);
const settle = (page: Page) => page.waitForTimeout(120);
/** Vertical distance between the active panel's centre and the copy slot's centre. */
const panelOffset = (page: Page, i: number) => page.evaluate((i) => {
  const slot = document.querySelector('.story-slot')!.getBoundingClientRect();
  const panel = document.querySelectorAll('.story-stage .panel')[i].getBoundingClientRect();
  return panel.top + panel.height / 2 - (slot.top + slot.height / 2);
}, i);

test.describe('desktop feature story @desktop', () => {
  test('copy follows its panel forward and backward, level with it', async ({ page }) => {
    await page.goto('/');
    for (const i of [0, 1, 2, 1, 0]) {
      await scrollToStage(page, i);
      await settle(page);
      expect(await expectedStage(page)).toBe(i);
      expect(await activeCopy(page)).toBe(titles[i]);
      expect(Math.abs(await panelOffset(page, i))).toBeLessThan(2);
    }
  });

  test('every stage gets the same scroll distance', async ({ page }) => {
    await page.goto('/');
    const switches = await page.evaluate(async () => {
      const steps = document.querySelector('.story-steps') as HTMLElement;
      const top = steps.getBoundingClientRect().top + scrollY;
      const range = steps.offsetHeight - innerHeight;
      const found: number[] = [];
      let last = 0;
      for (let o = 0; o <= range; o += 8) {
        scrollTo({ top: top + o, behavior: 'instant' });
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        const act = [...document.querySelectorAll<HTMLElement>('.story-copy')].findIndex((e) => e.dataset.active === 'true');
        if (act !== last) { found.push(o); last = act; }
      }
      return { found, range };
    });
    expect(switches.found).toHaveLength(2);
    const [a, b] = switches.found;
    const parts = [a, b - a, switches.range - b];
    for (const part of parts) expect(Math.abs(part - switches.range / 3)).toBeLessThan(40);
  });

  test('copy stays vertically centred and still while panels move', async ({ page }) => {
    await page.goto('/');
    const read = async () => page.evaluate(() => {
      const slot = document.querySelector('.story-slot')!.getBoundingClientRect();
      const panel = document.querySelectorAll('.story-stage .panel')[1].getBoundingClientRect();
      return { slotMid: slot.top + slot.height / 2, panelTop: panel.top, vh: innerHeight };
    });
    // Between stages 0 and 1 both panels are moving; the copy must not.
    await scrollToStage(page, 0, 0.9);
    const a = await read();
    await scrollToStage(page, 1, 0.05);
    const b = await read();
    expect(Math.abs(a.slotMid - a.vh / 2)).toBeLessThan(2);
    expect(Math.abs(a.slotMid - b.slotMid)).toBeLessThan(1);
    expect(a.panelTop - b.panelTop).toBeGreaterThan(50);
  });

  test('fast wheel scrolling lands on the correct copy', async ({ page }) => {
    await page.goto('/');
    await page.mouse.move(700, 450);
    for (let n = 0; n < 40; n++) {
      await page.mouse.wheel(0, 260 * (n % 9 < 6 ? 1 : -1));
      if (n % 3 === 0) {
        await settle(page);
        const { offset, range } = await geometry(page);
        // Skip samples inside the hysteresis band at a boundary.
        const nearBoundary = [1, 2].some((k) => Math.abs(offset - (range * k) / 3) < 30);
        if (!nearBoundary) expect(await activeCopy(page)).toBe(titles[await expectedStage(page)]);
      }
    }
  });

  test('no flicker for small reversals at a boundary', async ({ page }) => {
    await page.goto('/');
    await scrollToStage(page, 1, 0);
    await page.evaluate(() => scrollBy({ top: -30, behavior: 'instant' }));
    await settle(page);
    const start = await activeCopy(page);
    const seen = new Set<string | null>();
    for (const dy of [8, -8, 10, -10, 6, -6]) {
      await page.evaluate((dy) => scrollBy({ top: dy, behavior: 'instant' }), dy);
      await page.waitForTimeout(40);
      seen.add(await activeCopy(page));
    }
    expect([...seen]).toEqual([start]);
  });

  test('reload mid-story restores the right copy', async ({ page }) => {
    await page.goto('/');
    await scrollToStage(page, 2);
    await page.reload();
    await page.waitForTimeout(300); // scroll restoration differs by engine; check whatever position results
    await settle(page);
    expect(await activeCopy(page)).toBe(titles[await expectedStage(page)]);
  });

  test('last panel and copy leave together and do not cover Shorts', async ({ page }) => {
    await page.goto('/');
    await scrollToStage(page, 2, 0.99);
    await settle(page);
    expect(Math.abs(await panelOffset(page, 2))).toBeLessThan(2);
    await page.evaluate(() => scrollTo({ top: document.querySelector<HTMLElement>('.shorts')!.offsetTop - 100, behavior: 'instant' }));
    await settle(page);
    const overlap = await page.evaluate(() => {
      const slot = document.querySelector('.story-slot')!.getBoundingClientRect();
      const shorts = document.querySelector('.shorts')!.getBoundingClientRect();
      return slot.bottom > shorts.top + 1;
    });
    expect(overlap).toBe(false);
  });

  test('How it works anchor reaches the story', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'How it works' }).first().click();
    await page.waitForFunction(() => Math.abs(document.querySelector('#how-it-works')!.getBoundingClientRect().top) < 40, null, { timeout: 5000 });
    expect(await activeCopy(page)).toBe(titles[0]);
  });
});

test.describe('stacked story @mobile', () => {
  test('all three features are readable without pinning', async ({ page }) => {
    await page.goto('/');
    for (const t of titles) await expect(page.getByRole('heading', { name: t })).toBeVisible();
    await expect(page.locator('.story-rail')).toBeHidden();
  });
});
