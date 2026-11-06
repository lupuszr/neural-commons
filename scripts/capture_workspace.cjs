// Capture real, read-only workspace views for the README. Requires a running UI
// and Playwright from the DKG node-ui checkout. No fixture responses are injected.
// Usage: node scripts/capture_workspace.cjs URL EXPERIMENT_ID [OUTPUT_DIRECTORY]
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const { chromium } = require(require.resolve('@playwright/test', {
  paths: [path.join(root, '.runtime/dkg-source/packages/node-ui')]
}));
const [url, experiment, directory = path.join(root, 'docs/assets')] = process.argv.slice(2);
if (!url || !experiment) throw Error('Usage: node scripts/capture_workspace.cjs URL EXPERIMENT_ID [OUTPUT_DIRECTORY]');
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    fs.mkdirSync(directory, { recursive: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1040 }, deviceScaleFactor: 1 });
    page.setDefaultTimeout(30000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const target = new URL(url); target.hash = encodeURIComponent(experiment);
    await page.goto(target.href);
    await page.waitForFunction(() => !document.getElementById('workspace').hidden || !document.getElementById('connection').hidden);
    if (await page.locator('#connection').isVisible()) {
      if (!process.env.NC_UI_TOKEN) throw Error('This UI requires NC_UI_TOKEN in the environment.');
      await page.getByLabel('Participant access token', { exact: true }).fill(process.env.NC_UI_TOKEN);
      await page.getByRole('button', { name: 'Load participant', exact: true }).click();
    }
    await page.locator('#workspace').waitFor();
    assert.equal(await page.locator('#experiment-picker').inputValue(), experiment, 'Requested experiment is not available');
    const capture = async name => {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(directory, name), animations: 'disabled' });
      console.log(name);
    };
    await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    await capture('workspace.png');
    await page.getByRole('tab', { name: 'Assets', exact: true }).click();
    await page.getByLabel('Asset type', { exact: true }).selectOption('image');
    await page.waitForFunction(() => {
      const images = [...document.querySelectorAll('.asset-card img')];
      return images.length && images.every(image => image.complete && image.naturalWidth > 0);
    });
    await capture('workspace-assets.png');
    await page.getByRole('tab', { name: 'Collaborators', exact: true }).click();
    await page.locator('#collaborators .collaborator').first().waitFor();
    await capture('workspace-collaborators.png');
    await page.getByRole('button', { name: 'Shared experiments', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('shared-status').textContent.includes('Showing '), null, { timeout: 90000 });
    await page.locator('#graph-collaborators .collaborator').first().waitFor({ timeout: 90000 });
    assert.equal(await page.locator('#experiment-view').isVisible(), false);
    await capture('workspace-shared.png');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
