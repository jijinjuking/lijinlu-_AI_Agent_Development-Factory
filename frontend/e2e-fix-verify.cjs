// e2e-fix-verify.cjs — 验证 Artifacts / Context / StateManager 修复
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://127.0.0.1:5176';
const SCREENSHOT_DIR = path.join(__dirname, 'e2e-screenshots');

const ROUTES = [
  { path: '/artifacts', name: 'Artifacts' },
  { path: '/context', name: 'Context' },
  { path: '/state', name: 'StateManager' },
];

(async () => {
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    headless: true,
  });

  const results = [];

  for (const route of ROUTES) {
    const page = await browser.newPage();
    const url = `${BASE_URL}${route.path}`;

    try {
      const resp = await page.goto(url, { waitUntil: 'networkidle2', timeout: 20000 });
      await page.waitForTimeout(2000);

      const hasError = await page.evaluate(() => {
        const overlay = document.querySelector('vite-error-overlay');
        return !!overlay;
      });

      const bodyText = await page.evaluate(() => document.body.innerText);
      const hasContent = bodyText.length > 200 && !bodyText.includes('does not provide an export');

      const screenshotPath = path.join(SCREENSHOT_DIR, `${route.name}_fixed.png`);
      await page.screenshot({ path: screenshotPath, fullPage: false });

      results.push({
        name: route.name,
        status: resp?.status() || 0,
        hasError,
        hasContent,
        pass: resp?.status() === 200 && !hasError && hasContent,
        screenshot: screenshotPath,
      });
    } catch (e) {
      results.push({ name: route.name, status: 0, hasError: true, hasContent: false, pass: false, error: e.message });
    } finally {
      await page.close();
    }
  }

  await browser.close();

  console.log('\n========== 修复验证结果 ==========\n');
  let allPass = true;
  for (const r of results) {
    const icon = r.pass ? '✅' : '❌';
    console.log(`${icon} ${r.name}: HTTP ${r.status} | ErrorOverlay=${r.hasError} | HasContent=${r.hasContent}`);
    if (!r.pass) allPass = false;
  }
  console.log('\n==================================');
  console.log(allPass ? '✅ 全部通过' : '❌ 有失败项');
  process.exit(allPass ? 0 : 1);
})();
