const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const base = process.env.USAGE_TEST_URL;
  assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    await context.addCookies([{ name: 'ap_session', value: 'usage-admin', url: base }]);
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base);await page.waitForFunction(() => state.authed && window.MeimeiMotion);
    await page.evaluate(() => closeSidebarTools());await page.waitForTimeout(300);
    for (let attempt = 0; attempt < 3; attempt++) {
      await page.locator('#toggleSidebarTools').click();
      const sample = await page.evaluate(async () => {
        const card = document.querySelector('.sidebar-tool-card');
        const opacity = [], paths = new Set(), start = performance.now();
        while (performance.now() - start < 450) {
          await new Promise(requestAnimationFrame);
          opacity.push(Number(getComputedStyle(card).opacity));
          for (const animation of card.getAnimations()) {
            if (animation.effect.getKeyframes().some(frame => frame.opacity !== undefined)) paths.add(animation);
          }
        }
        return { paths: paths.size, drops: opacity.filter((value, i) => i && opacity[i - 1] - value > .05).length, final: opacity.at(-1) };
      });
      console.log(JSON.stringify({ attempt, ...sample }));
      assert.equal(sample.paths, 1, 'Exactly one opacity entrance');
      assert.equal(sample.drops, 0, 'Opacity must not restart');assert.equal(sample.final, 1);
      await page.evaluate(() => openSidebarTools());
      assert.equal(await page.locator('.sidebar-tool-card').first().evaluate(el => el.getAnimations().length), 0, 'Already-open tools must not replay');
      await page.locator('#toggleSidebarTools').click();await page.waitForTimeout(300);
      assert.equal(await page.locator('#toggleSidebarTools').getAttribute('aria-expanded'), 'false');
    }
    await page.locator('#toggleSidebarTools').click();await page.locator('#openPromptLibrary').click();await page.waitForTimeout(300);
    assert.equal(await page.locator('#promptDialog').isVisible(), true);
    await page.evaluate(() => closePromptLibrary());
    await page.emulateMedia({ reducedMotion: 'reduce' });await page.evaluate(() => openSidebarTools());
    assert.equal(await page.locator('.sidebar-tool-card').first().evaluate(el => el.getAnimations().length), 0);
    assert.deepEqual(errors, []);console.log('PASS: single entrance, repeated toggle, tool action, reduced motion');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
