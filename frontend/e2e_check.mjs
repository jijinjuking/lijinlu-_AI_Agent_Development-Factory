// ============================================================
// E2E Browser Check — 逐页验证渲染和交互
// 使用 Puppeteer 批量检查 24 个页面
// ============================================================

import puppeteer from 'puppeteer';

const ROUTES = [
  { path: '/', name: 'Dashboard' },
  { path: '/agents', name: 'Agents' },
  { path: '/pipelines', name: 'Pipelines' },
  { path: '/traces', name: 'Traces' },
  { path: '/memory', name: 'Memory' },
  { path: '/skills', name: 'Skills' },
  { path: '/costs', name: 'Costs' },
  { path: '/settings', name: 'Settings' },
  { path: '/state', name: 'State Manager' },
  { path: '/artifacts', name: 'Artifacts' },
  { path: '/tools', name: 'Tools' },
  { path: '/context', name: 'Context' },
  { path: '/event-replay', name: 'Event Replay' },
  { path: '/state-replay', name: 'State Replay' },
  { path: '/tasks', name: 'Tasks' },
  { path: '/events', name: 'Events' },
  { path: '/runtime-ops', name: 'Runtime Ops' },
  { path: '/evaluation', name: 'Evaluation' },
  { path: '/k8s', name: 'K8s' },
  { path: '/multi-node', name: 'Multi-Node' },
  { path: '/marketplace', name: 'Marketplace' },
  { path: '/federation', name: 'Federation' },
  { path: '/tenants', name: 'Tenants' },
  { path: '/performance', name: 'Performance' },
  { path: '/projects', name: 'Projects' },
];

async function checkPage(browser, { path, name }) {
  const result = {
    name,
    path,
    status: 'OK',
    title: '',
    errors: [],
    apiErrors: [],
    bodyText: '',
  };

  const page = await browser.newPage();

  // Collect console errors
  page.on('console', msg => {
    if (msg.type() === 'error') {
      result.errors.push(msg.text());
    }
  });

  // Collect page errors (uncaught exceptions)
  page.on('pageerror', err => {
    result.errors.push(err.message);
  });

  // Intercept network responses to detect API errors
  page.on('response', resp => {
    if (resp.url().includes('/api/') && resp.status() >= 400) {
      result.apiErrors.push(`${resp.status()} ${resp.url()}`);
    }
  });

  try {
    await page.goto(`http://localhost:5176${path}`, {
      waitUntil: 'networkidle2',
      timeout: 25000,
    });

    result.title = await page.title();
    // Use body innerText, fallback to main/content
    result.bodyText = await page.evaluate(() => {
      // Try multiple selectors for main content
      const selectors = [
        '.ant-layout-content',
        'main',
        '[class*="content"]',
        'body',
      ];
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText.trim().length > 50) {
          return el.innerText.substring(0, 300).replace(/\s+/g, ' ').trim();
        }
      }
      return document.body.innerText.substring(0, 300).replace(/\s+/g, ' ').trim();
    });

    // Check for common error indicators
    if (!result.bodyText || result.bodyText.length < 20) {
      result.status = 'ISSUE';
      result.errors.push('Body text too short or empty (possible white screen)');
    }

    if (result.bodyText.includes('Something went wrong') || result.bodyText.includes('Error:')) {
      result.status = 'ISSUE';
    }
  } catch (e) {
    result.status = 'ERROR';
    result.errors.push(`Navigation failed: ${e.message}`);
  }

  await page.close();
  return result;
}

async function main() {
  console.log('Starting E2E browser checks...\n');

  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  const results = [];
  for (const route of ROUTES) {
    process.stdout.write(`  [${results.length + 1}/${ROUTES.length}] ${route.name}... `);
    const r = await checkPage(browser, route);
    results.push(r);

    const icon = r.status === 'OK' ? '✅' : '❌';
    console.log(`${icon} ${r.status}`);
    if (r.errors.length > 0) {
      for (const e of r.errors) console.log(`       Error: ${e.substring(0, 120)}`);
    }
    if (r.apiErrors.length > 0) {
      for (const e of r.apiErrors) console.log(`       API: ${e}`);
    }
  }

  await browser.close();

  console.log('\n========== SUMMARY ==========');
  const ok = results.filter(r => r.status === 'OK');
  const issues = results.filter(r => r.status !== 'OK');
  console.log(`Total: ${results.length}, OK: ${ok.length}, Issues: ${issues.length}\n`);

  if (issues.length > 0) {
    console.log('Pages with issues:');
    for (const r of issues) {
      console.log(`  ${r.path} (${r.name})`);
      for (const e of r.errors) console.log(`    - ${e.substring(0, 150)}`);
      for (const e of r.apiErrors) console.log(`    - API: ${e}`);
    }
  }

  // Write JSON report
  const report = {
    timestamp: new Date().toISOString(),
    total: results.length,
    ok: ok.length,
    issues: issues.length,
    pages: results,
  };

  const fs = await import('fs');
  fs.writeFileSync('./e2e_report.json', JSON.stringify(report, null, 2));
  console.log('\nReport saved to e2e_report.json');
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
