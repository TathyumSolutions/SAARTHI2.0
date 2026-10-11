// Renders <work_dir>/doc.html to PDF with headless Chromium.
// Usage: node print.js <work_dir> <out.pdf>
const { chromium } = require('playwright');
(async () => {
  const dir = process.argv[2], out = process.argv[3];
  // PLAYWRIGHT_CHROMIUM_PATH lets you point at an already-installed Chromium.
  const b = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {});
  const p = await b.newPage();
  await p.goto('file://' + dir + '/doc.html');
  await p.waitForFunction(() => window.__done === true, null, { timeout: 120000 });
  const err = await p.evaluate(() => window.__err || null);
  const bad = await p.evaluate(() => [...document.querySelectorAll('.mermaid')].filter(d => !d.querySelector('svg') || d.textContent.includes('Syntax error')).length);
  if (err || bad) { console.error(`Mermaid failed: ${bad} diagram(s) did not render${err ? ' - ' + err : ''}`); process.exit(1); }
  await p.pdf({ path: out, format: 'A4', printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<div style="font-size:7px;width:100%;text-align:right;padding-right:15mm;color:#888">Saarthi 2.0 — Detailed Design Document</div>',
    footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#888"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    margin: { top: '18mm', bottom: '16mm', left: '15mm', right: '15mm' } });
  await b.close();
})();
