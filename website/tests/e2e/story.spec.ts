import { expect, test, type Page } from '@playwright/test';

const titles = ['Start with a question', 'Find the unexpected winners', 'See the idea behind the views'];

/** Independent expectation: the stage whose screenshot centre is nearest the viewport centre. */
const expectedStage = (page: Page) => page.evaluate(() => {
  const mid = innerHeight / 2;
  const d = [...document.querySelectorAll('.story-stage .panel')].map((el) => {
    const r = el.getBoundingClientRect();
    return Math.abs(r.top + r.height / 2 - mid);
  });
  return d.indexOf(Math.min(...d));
});
const activeCopy = (page: Page) => page.locator('.story-copy[data-active="true"] .feature-title').textContent();
/** Scrolls so screenshot i is centred, plus an optional offset. */
const scrollToStage = (page: Page, i: number, offset = 0) => page.evaluate(([i, offset]) => {
  const stage = document.querySelectorAll('.story-step')[i] as HTMLElement;
  // A step's screenshot is centred from the moment its step reaches the viewport top.
  scrollTo({ top: stage.getBoundingClientRect().top + scrollY + offset, behavior: 'instant' });
}, [i, offset]);
const settle = (page: Page) => page.waitForTimeout(120);
/** Vertical distance between screenshot i's centre and the copy slot's centre. */
const panelOffset = (page: Page, i: number) => page.evaluate((i) => {
  const slot = document.querySelector('.story-slot')!.getBoundingClientRect();
  const panel = document.querySelectorAll('.story-stage .panel')[i].getBoundingClientRect();
  return panel.top + panel.height / 2 - (slot.top + slot.height / 2);
}, i);

test.describe('desktop feature story @desktop', () => {
  test('copy follows its panel forward and backward, level with it', async ({ page }) => {
    await page.goto('/');
    for (const i of [0, 1, 2, 1, 0]) {
      await scrollToStage(page, i, i === 0 ? 0 : 60);
      await settle(page);
      expect(await expectedStage(page)).toBe(i);
      expect(await activeCopy(page)).toBe(titles[i]);
      expect(Math.abs(await panelOffset(page, i))).toBeLessThan(2);
    }
  });

  test('first screenshot starts moving as soon as it is centred; later ones hold briefly', async ({ page }) => {
    await page.goto('/');
    const top = (i: number) => page.evaluate((i) => document.querySelectorAll('.story-stage .panel')[i].getBoundingClientRect().top, i);
    await scrollToStage(page, 0);
    const a = await top(0);
    await scrollToStage(page, 0, 40);
    expect(a - (await top(0))).toBeCloseTo(40, 0); // no hold on the first step
    await scrollToStage(page, 1, 10);
    const b = await top(1);
    await scrollToStage(page, 1, 150);
    expect(Math.abs(b - (await top(1)))).toBeLessThan(1); // second step holds
  });

  test('copy stays vertically centred and still while panels move', async ({ page }) => {
    await page.goto('/');
    const read = async () => page.evaluate(() => {
      const slot = document.querySelector('.story-slot')!.getBoundingClientRect();
      const panel = document.querySelectorAll('.story-stage .panel')[1].getBoundingClientRect();
      return { slotMid: slot.top + slot.height / 2, panelTop: panel.top, vh: innerHeight };
    });
    // Between stages 0 and 1 both screenshots are moving; the copy must not.
    await scrollToStage(page, 0, 100);
    const a = await read();
    await scrollToStage(page, 0, 400);
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
        const inStory = await page.evaluate(() => {
          const r = document.querySelector('.story-steps')!.getBoundingClientRect();
          return r.top < innerHeight / 2 && r.bottom > innerHeight / 2;
        });
        if (inStory) expect(await activeCopy(page)).toBe(titles[await expectedStage(page)]);
      }
    }
  });

  test('no flicker for small reversals at a boundary', async ({ page }) => {
    await page.goto('/');
    // Put the midpoint between screenshots 0 and 1 at the viewport centre, then step 30px back.
    await page.evaluate(() => {
      const [a, b] = [...document.querySelectorAll('.story-stage .panel')].map((el) => el.getBoundingClientRect());
      const boundary = (a.top + a.height / 2 + b.top + b.height / 2) / 2;
      scrollTo({ top: scrollY + boundary - innerHeight / 2 - 30, behavior: 'instant' });
    });
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
    await page.evaluate(() => { const s = document.querySelector('.story-steps') as HTMLElement; scrollTo({ top: s.getBoundingClientRect().top + scrollY + s.offsetHeight - innerHeight - 2, behavior: 'instant' }); });
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
