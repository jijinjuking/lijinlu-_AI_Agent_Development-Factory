// e2e-validate.js — 端到端验证脚本
// 用法: node e2e-validate.js

const puppeteer = require('puppeteer');

const BASE_URL = 'http://127.0.0.1:5176';
const API_BASE = 'http://127.0.0.1:8002/api/v1';

const ROUTES = [
  { path: '/', name: 'Dashboard' },
  { path: '/agents', name: 'Agents' },
  { path: '/pipelines', name: 'Pipelines' },
  { path: '/traces', name: 'Traces' },
  { path: '/memory', name: 'Memory' },
  { path: '/skills', name: 'Skills' },
  { path: '/costs', name: 'Costs' },
  { path: '/settings', name: 'Settings' },
  { path: '/state', name: 'StateManager' },
  { path: '/artifacts', name: 'Artifacts' },
  { path: '/tools', name: 'Tools' },
  { path: '/context', name: 'Context' },
];

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  const results = [];

  for (const route of ROUTES) {
    const url = `${BASE_URL}${route.path}`;
    try {
      console.log(`\n→ Testing [${route.name}] ${url}`);
      
      const res = await page.goto(url, { waitUntil: 'networkidle2', timeout: 15000 });
      const status = res?.status() || 0;
      
      // 检查页面是否加载（不是空白页）
      const title = await page.title();
      const hasContent = await page.evaluate(() => {
        const root = document.getElementById('root');
        return root && root.innerHTML.length > 100;
      });

      // 检查是否有 React 错误
      const hasError = await page.evaluate(() => {
        const body = document.body.innerText || '';
        return body.includes('Error Boundary') || 
               body.includes('Something went wrong') ||
               document.querySelector('.ant-result-error') !== null;
      });

      // 截图
      const screenshotPath = `N:/WorkBuddy/2026-05-29-01-14-11/ai-agent-os/frontend/e2e-screenshots/${route.name}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: false });

      // 检查 console errors
      const logs = [];
      page.on('console', msg => {
        if (msg.type() === 'error') logs.push(msg.text());
      });

      results.push({
        name: route.name,
        path: route.path,
        httpStatus: status,
        title,
        hasContent,
        hasError,
        screenshot: screenshotPath,
      });

      console.log(`  HTTP: ${status} | Title: "${title}" | Content: ${hasContent} | Error: ${hasError}`);

    } catch (err) {
      results.push({
        name: route.name,
        path: route.path,
        error: err.message,
      });
      console.log(`  ✗ FAILED: ${err.message}`);
    }
  }

  await browser.close();

  // 汇总
  console.log('\n' + '='.repeat(60));
  console.log('E2E VALIDATION SUMMARY');
  console.log('='.repeat(60));
  
  let pass = 0, fail = 0;
  for (const r of results) {
    if (r.error) {
      console.log(`  ✗ ${r.name}: ${r.error}`);
      fail++;
    } else if (r.hasError) {
      console.log(`  ⚠ ${r.name}: Page rendered but has errors`);
      fail++;
    } else if (r.hasContent) {
      console.log(`  ✓ ${r.name}: OK (HTTP ${r.httpStatus})`);
      pass++;
    } else {
      console.log(`  ⚠ ${r.name}: Page loaded but no content (HTTP ${r.httpStatus})`);
      fail++;
    }
  }
  console.log('='.repeat(60));
  console.log(`Pass: ${pass} | Fail: ${fail} | Total: ${results.length}`);
  console.log(`Screenshots: N:/WorkBuddy/2026-05-29-01-14-11/ai-agent-os/frontend/e2e-screenshots/`);
})();
