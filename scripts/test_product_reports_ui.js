const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const base = process.env.READER_TEST_URL;
  assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addCookies([{ name: 'ap_session', value: 'reader-a', url: base }]);
    const page = await context.newPage(), errors = [], saved = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => {
      if (request.method() === 'PUT' && /\/api\/admin\/users\//.test(request.url())) saved.push(request.postDataJSON());
    });
    await page.goto(base);
    await page.waitForFunction(() => state.authed);
    await page.evaluate(() => { openSettings(); switchAdminSection('accounts'); });
    await page.waitForFunction(() => state.adminUsers?.some(user => user.username === 'czq'));
    await page.evaluate(async () => {
      const user = state.adminUsers.find(item => item.username === 'czq');
      const res = await adminApi(`/api/admin/users/${user.id}`, { method: 'PUT', body: JSON.stringify({ product_reports_enabled: false, product_push_enabled: false }) });
      if (!res.ok) throw new Error('产品推送隔离初始状态设置失败');
      await loadAdminUsers();
    });
    await page.evaluate(() => fillAccountForm(state.adminUsers.find(user => user.username === 'czq')));
    assert.equal(await page.locator('#accountProductReportControls').isVisible(), true);
    assert.equal(await page.locator('#accountDailyReports').isChecked(), false);
    await page.getByText('开放每日产品推送', { exact: true }).click();
    await page.getByText('产品推送通知', { exact: true }).click();
    await page.locator('#saveAccount').click();
    await page.waitForFunction(() => document.querySelector('#accountStatus').textContent.includes('已保存'));
    assert.equal(saved.at(-1).product_reports_enabled, true);
    assert.equal(saved.at(-1).product_push_enabled, true);
    assert.equal(saved.at(-1).daily_reports_enabled, false);
    await page.evaluate(() => fillAccountForm(state.adminUsers.find(user => user.username === 'czq')));
    assert.equal(await page.locator('#accountProductReports').isChecked(), true);
    assert.equal(await page.locator('#accountProductPush').isChecked(), true);
    await page.screenshot({ path: '/private/tmp/meimei-products-admin-desktop.png' });

    await page.evaluate(() => fillAccountForm(state.adminUsers.find(user => user.id === 'reader-a')));
    assert.equal(await page.locator('#accountProductReportControls').isVisible(), false);
    assert.equal(await page.locator('#accountProductReports').isDisabled(), true);
    await page.locator('#saveAccount').click();
    await page.waitForFunction(() => document.querySelector('#accountStatus').textContent.includes('已保存'));
    assert.equal(Object.hasOwn(saved.at(-1), 'product_reports_enabled'), false);
    assert.equal(Object.hasOwn(saved.at(-1), 'product_push_enabled'), false);

    await page.evaluate(() => { resetAccountForm(); document.querySelector('#accountUsername').value = 'feng'; syncProductReportAccountControls(); });
    assert.equal(await page.locator('#accountProductReportControls').isVisible(), true);
    await page.locator('#accountUsername').fill('another-user');
    assert.equal(await page.locator('#accountProductReportControls').isVisible(), false);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { closeSidebar(); openSettings(); switchAdminSection('accounts'); });
    await page.waitForFunction(() => document.querySelector('#sidebar').getBoundingClientRect().right <= 0);
    await page.waitForFunction(() => state.adminUsers?.some(user => user.username === 'czq'));
    await page.evaluate(() => fillAccountForm(state.adminUsers.find(user => user.username === 'czq')));
    await page.locator('#accountProductReports').scrollIntoViewIfNeeded();
    await page.screenshot({ path: '/private/tmp/meimei-products-admin-mobile.png' });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);

    await page.evaluate(() => switchAdminSection('system'));
    await page.waitForFunction(() => !document.querySelector('#productReportsPaused').disabled);
    const dailyPaused = await page.locator('#dailyReportsPaused').isChecked();
    await page.getByText('暂停产品推送', { exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#productReportsPauseStatus').textContent.includes('已暂停'));
    assert.equal(await page.locator('#dailyReportsPaused').isChecked(), dailyPaused);
    assert.equal(await page.evaluate(async () => (await (await adminApi('/api/admin/product-report-settings')).json()).paused), true);
    await page.getByText('暂停产品推送', { exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#productReportsPauseStatus').textContent.includes('已恢复'));
    assert.equal(await page.locator('#dailyReportsPaused').isChecked(), dailyPaused);
    assert.deepEqual(errors, []);
    console.log('每日产品推送后台权限、独立通知与暂停、桌面和手机布局回归通过');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
