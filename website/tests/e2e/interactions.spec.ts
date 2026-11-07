import { expect, test } from '@playwright/test';

test.describe('install command @all', () => {
  test('shows Copied only after a successful write, then resets', async ({ page, browserName, context }) => {
    test.skip(browserName === 'webkit', 'WebKit automation cannot grant clipboard permission');
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.goto('/');
    const button = page.locator('.hero .install-copy');
    const width = await button.evaluate((el) => el.getBoundingClientRect().width);
    await button.click();
    await expect(page.locator('.hero .install')).toHaveAttribute('data-status', 'copied');
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('npx yuben-app@latest');
    expect(await button.evaluate((el) => el.getBoundingClientRect().width)).toBe(width);
    await button.click(); // repeated click keeps a single, consistent state
    await expect(page.locator('.hero .install')).toHaveAttribute('data-status', 'copied');
    await expect(page.locator('.hero .install')).toHaveAttribute('data-status', 'idle', { timeout: 4000 });
  });

  test('a blocked clipboard selects the command instead of claiming success', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', { value: { writeText: () => Promise.reject(new DOMException('no', 'NotAllowedError')) } });
    });
    await page.goto('/');
    await page.locator('.hero .install-copy').click();
    await expect(page.locator('.hero .install')).toHaveAttribute('data-status', 'failed');
    await expect(page.locator('.hero .install-hint')).toContainText('command is selected');
    expect(await page.evaluate(() => getSelection()?.toString())).toBe('npx yuben-app@latest');
  });
});

test.describe('faq @all', () => {
  test('toggles with keyboard and mouse', async ({ page }) => {
    await page.goto('/');
    const second = page.locator('.faq-item').nth(1);
    await expect(second).not.toHaveAttribute('open');
    await second.locator('summary').click();
    await expect(second).toHaveAttribute('open');
    await expect(second.locator('.faq-answer')).toContainText('Ollama');
    await second.locator('summary').focus();
    await page.keyboard.press('Enter');
    await expect(second).not.toHaveAttribute('open');
  });
});

test.describe('shorts dialog @all', () => {
  test('creates the embed on activation, removes it on Escape and restores focus', async ({ page }) => {
    await page.route(/youtube(-nocookie)?\.com/, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<p>stub</p>' }));
    await page.goto('/');
    await expect(page.locator('iframe')).toHaveCount(0);
    const card = page.getByRole('link', { name: 'Play the first YuBen Short' });
    await card.scrollIntoViewIfNeeded();
    await card.click();
    const frame = page.locator('.short-dialog iframe');
    await expect(frame).toHaveAttribute('src', /R24JLVqW9pg/);
    await expect(page.getByRole('link', { name: /Watch on YouTube/ })).toHaveAttribute('href', /shorts\/R24JLVqW9pg/);
    await page.keyboard.press('Escape');
    await expect(page.locator('iframe')).toHaveCount(0);
    await expect(card).toBeFocused();
  });

  test('close button closes the second Short', async ({ page }) => {
    await page.route(/youtube(-nocookie)?\.com/, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '' }));
    await page.goto('/');
    const card = page.getByRole('link', { name: 'Play the second YuBen Short' });
    await card.scrollIntoViewIfNeeded();
    await card.click();
    await expect(page.locator('.short-dialog iframe')).toHaveAttribute('src', /opb18eNVrn0/);
    await page.getByRole('button', { name: 'Close video' }).click();
    await expect(page.locator('iframe')).toHaveCount(0);
  });
});

test.describe('demo video @all', () => {
  const state = (page: import('@playwright/test').Page) =>
    page.locator('video').evaluate((v: HTMLVideoElement) => ({ paused: v.paused, muted: v.muted, time: v.currentTime }));

  test('autoplays muted, user pause survives scrolling away and back', async ({ page }) => {
    await page.goto('/');
    await expect.poll(async () => (await state(page)).paused, { timeout: 10000 }).toBe(false);
    expect((await state(page)).muted).toBe(true);
    await page.getByRole('button', { name: 'Pause demo' }).click();
    await expect(page.getByRole('button', { name: 'Play demo' })).toBeVisible();
    await page.evaluate(() => scrollTo({ top: 3000, behavior: 'instant' }));
    await page.waitForTimeout(300);
    await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
    await page.waitForTimeout(500);
    expect((await state(page)).paused).toBe(true);
  });

  test('pauses offscreen and resumes from the same time', async ({ page }) => {
    await page.goto('/');
    // Playwright's WebKit restarts from 0 if paused in the first ~0.5s (no seek event); resume is checked after 2s.
    await expect.poll(async () => (await state(page)).time, { timeout: 10000 }).toBeGreaterThan(2);
    await page.evaluate(() => scrollTo({ top: 4000, behavior: 'instant' }));
    await expect.poll(async () => (await state(page)).paused).toBe(true);
    const t = (await state(page)).time;
    await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
    await expect.poll(async () => (await state(page)).paused).toBe(false);
    expect((await state(page)).time).toBeGreaterThanOrEqual(t);
  });

  test('sound button toggles real muted state', async ({ page }) => {
    await page.goto('/');
    await expect.poll(async () => (await state(page)).paused, { timeout: 10000 }).toBe(false);
    await page.getByRole('button', { name: 'Turn demo sound on' }).click();
    expect((await state(page)).muted).toBe(false);
    await expect(page.getByRole('button', { name: 'Turn demo sound off' })).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'Turn demo sound off' }).click();
    expect((await state(page)).muted).toBe(true);
  });

  test('opening a Short pauses the demo', async ({ page }) => {
    await page.route(/youtube(-nocookie)?\.com/, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '' }));
    await page.goto('/');
    await expect.poll(async () => (await state(page)).paused, { timeout: 10000 }).toBe(false);
    await page.getByRole('link', { name: 'Play the first YuBen Short' }).click();
    expect((await state(page)).paused).toBe(true);
  });

  test('a failed source shows a working fallback', async ({ page }) => {
    await page.route('**/yuben-demo-light.mp4', (route) => route.fulfill({ status: 404, body: '' }));
    await page.goto('/');
    await expect(page.locator('.demo-status')).toContainText('Video unavailable', { timeout: 10000 });
    await expect(page.getByRole('button', { name: 'Play demo' })).toBeVisible();
  });

  test('rejected autoplay offers a play button', async ({ page }) => {
    await page.addInitScript(() => {
      HTMLMediaElement.prototype.play = function () { return Promise.reject(new DOMException('blocked', 'NotAllowedError')); };
    });
    await page.goto('/');
    await expect(page.locator('.demo-fallback')).toBeVisible({ timeout: 10000 });
  });
});

test.describe('reduced motion @all', () => {
  test.use({ colorScheme: 'light' });
  test('poster only until the user plays; content visible', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await page.waitForTimeout(800);
    expect(await page.locator('video').evaluate((v: HTMLVideoElement) => v.paused)).toBe(true);
    await expect(page.getByRole('button', { name: 'Play demo' })).toBeVisible();
    for (const sel of ['.shorts', '.models', '.faq', '.closing']) {
      expect(await page.locator(sel).evaluate((el) => getComputedStyle(el).opacity)).toBe('1');
    }
  });
});

test.describe('header @desktop', () => {
  test('links and star button point to the right places', async ({ page }) => {
    await page.goto('/');
    const nav = page.getByRole('navigation', { name: 'Main' });
    await expect(nav.getByRole('link', { name: 'Features' })).toHaveAttribute('href', '#features');
    await expect(nav.getByRole('link', { name: 'Docs' })).toHaveAttribute('href', 'https://github.com/shkuratovdesigner/yuben-app#readme');
    await expect(page.getByRole('link', { name: /YuBen on GitHub, \d+ stars/ }).first()).toHaveAttribute('href', 'https://github.com/shkuratovdesigner/yuben-app');
    await expect(page.locator('.menu-toggle')).toBeHidden();
  });
});

test.describe('mobile menu @mobile', () => {
  test('opens, traps focus, closes with Escape and restores scroll', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => scrollTo({ top: 30, behavior: 'instant' }));
    const toggle = page.getByRole('button', { name: 'Open menu' });
    await toggle.click();
    const locked = await page.evaluate(() => -parseFloat(document.body.style.top));
    const dialog = page.getByRole('dialog', { name: 'Menu' });
    await expect(dialog).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByRole('button', { name: 'Close menu' })).toBeFocused();
    const gh = dialog.getByRole('link', { name: /GitHub/ });
    expect((await gh.boundingBox())!.height).toBe(60);
    for (let i = 0; i < 8; i++) await page.keyboard.press('Tab');
    expect(await page.evaluate(() => !!document.activeElement?.closest('#mobile-menu'))).toBe(true);
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(toggle).toBeFocused();
    expect(locked).toBeGreaterThan(0);
    expect(await page.evaluate(() => scrollY)).toBe(locked);
  });

  test('anchor selection closes the menu and scrolls to the section', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Open menu' }).click();
    await page.getByRole('dialog').getByRole('link', { name: 'Features' }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
    await page.waitForFunction(() => Math.abs(document.querySelector('#features')!.getBoundingClientRect().top) < 40, null, { timeout: 5000 });
  });

  test('menu glyph sits in a 44px hit target', async ({ page }) => {
    await page.goto('/');
    const box = (await page.locator('.menu-toggle').boundingBox())!;
    expect(box.width).toBe(44);
    expect(box.height).toBe(44);
  });

  test('Shorts gallery swipes with a visible peek', async ({ page }) => {
    await page.goto('/');
    const track = page.locator('.shorts-track');
    await track.scrollIntoViewIfNeeded();
    const second = await page.locator('.short-card').nth(1).boundingBox();
    expect(second!.x).toBeLessThan(390);
    await track.evaluate((el) => el.scrollTo({ left: 400, behavior: 'instant' }));
    await expect(page.locator('.shorts-dots button').nth(1)).toHaveAttribute('data-on', 'true');
  });
});
