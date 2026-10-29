const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const base = process.env.READER_TEST_URL;
  assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addCookies([{ name: 'ap_session', value: 'reader-a', url: base }]);
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base); await page.waitForFunction(() => state.authed);
    await page.evaluate(() => { openSettings(); switchAdminSection('accounts'); });
    await page.waitForFunction(() => state.adminUsers?.length >= 2);
    await page.evaluate(async () => {
      await adminApi('/api/admin/users/reader-b', { method: 'PUT', body: JSON.stringify({ daily_reports_enabled: false, daily_push_enabled: false }) });
      await loadAdminUsers();
    });
    await page.evaluate(() => fillAccountForm(state.adminUsers.find(u => u.id === 'reader-b')));
    assert.equal(await page.locator('#accountDailyReports').isChecked(), false);
    await page.getByText('开放研发日报', { exact: true }).click();
    await page.getByText('日报推送通知', { exact: true }).click();
    await page.locator('#saveAccount').click();
    await page.waitForFunction(() => document.querySelector('#accountStatus').textContent.includes('已保存'));
    await page.evaluate(() => fillAccountForm(state.adminUsers.find(u => u.id === 'reader-b')));
    assert.equal(await page.locator('#accountDailyPush').isChecked(), true);
    await page.waitForTimeout(350);
    await page.screenshot({ path: '/private/tmp/meimei-reports-admin-desktop.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { closeSidebar(); openSettings(); switchAdminSection('accounts'); });
    await page.waitForFunction(() => state.adminUsers?.length >= 2);
    await page.evaluate(() => fillAccountForm(state.adminUsers.find(u => u.id === 'reader-b')));
    await page.locator('#accountDailyReports').scrollIntoViewIfNeeded();
    await page.waitForTimeout(350);
    await page.screenshot({ path: '/private/tmp/meimei-reports-admin-mobile.png' });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.evaluate(() => switchAdminSection('system'));
    await page.getByText('暂停日报推送', { exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#dailyReportsPauseStatus').textContent.includes('已暂停'));
    await page.getByText('暂停日报推送', { exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#dailyReportsPauseStatus').textContent.includes('已恢复'));
    assert.deepEqual(errors, []);
    console.log('日报后台桌面/手机开关保存与总暂停回归通过');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
