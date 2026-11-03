// Browser regression checks against a copy of a completed participant journal.
// No DKG services, evaluator processes or external writes are started.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const net = require('node:net');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
if (!process.argv[2]) throw Error('Usage: node scripts/ui_check.cjs PARTICIPANT_HOME');
const source = path.resolve(process.argv[2]);
const { chromium } = require(require.resolve('@playwright/test', { paths: [path.join(root, '.runtime/dkg-source/packages/node-ui')] }));
(async () => {
  const home = fs.mkdtempSync(path.join(root, '.runtime/ui-test-'));
  fs.cpSync(source, home, { recursive: true });
  const config = JSON.parse(fs.readFileSync(path.join(home, 'config.json'), 'utf8'));
  const token = fs.readFileSync(config.artifact_token_file, 'utf8').trim();
  const listener = net.createServer(); await new Promise(r => listener.listen(0, '127.0.0.1', r));
  const port = listener.address().port; await new Promise(r => listener.close(r));
  const server = cp.spawn(path.join(root, 'target/debug/nc'), ['--home', home, 'serve', '--port', String(port)], { stdio: 'ignore' });
  const exited = new Promise(r => server.once('exit', r));
  let browser;
  try {
    const url = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 80; i++) { try { if ((await fetch(url)).ok) break; } catch {} await new Promise(r => setTimeout(r, 100)); }
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(url);
    async function login(value = token) {
      await page.getByLabel('Participant access token').fill(value);
      await page.getByRole('button', { name: 'Load participant' }).click();
    }
    await login('wrong-token');
    await page.getByRole('status').filter({ hasText: 'HTTP 401' }).waitFor();
    assert.equal(await page.locator('#workspace').isVisible(), false);
    await login(); await page.getByRole('status').filter({ hasText: 'Loaded from' }).waitFor();
    const state = await (await fetch(`${url}/api/state`, { headers: { Authorization: `Bearer ${token}` } })).json();
    assert.ok(state.jobs.length || state.records.length, 'Use a completed participant journal');
    assert.ok(await page.locator('.experiment').count(), 'No experiments rendered');
    assert.equal(await page.getByLabel('Participant access token').inputValue(), '', 'Token retained in field');
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0, 'Token persisted');
    const activeSpec = await page.locator('.experiment[aria-pressed=true]').getAttribute('data-experiment');
    const artifact = async id => (await fetch(`${url}/api/artifact-metadata/${id}`, { headers: { Authorization: `Bearer ${token}` } })).json();
    const spec = await artifact(activeSpec);
    if (await page.locator('#open-continuation').isEnabled()) {
      // Inspect the real form and payload, but never start a model in browser QA.
      const requests = [];
      await page.route('**/api/continuations', async route => {
        if (route.request().method() !== 'POST') return route.continue();
        const body = route.request().postDataJSON(); requests.push(body);
        return route.fulfill({ status: requests.length === 1 ? 503 : 200, json: requests.length === 1 ? { error: 'Inert test response; retry safely' } : { id: body.id, status: 'queued' } });
      });
      await page.getByRole('button', { name: 'Continue from candidate' }).click();
      await page.getByLabel('New task directory').fill('/inert/ui-test/task');
      await page.getByLabel('Controller model', { exact: true }).fill('ui-test-only');
      await page.screenshot({ path: path.join(root, '.runtime/ui-continuation-form.png'), fullPage: true });
      await page.getByRole('button', { name: 'Start controller', exact: true }).click();
      await page.locator('#continuation-error').filter({ hasText: 'retry this request safely' }).waitFor();
      await page.getByRole('button', { name: 'Start controller', exact: true }).click();
      await page.locator('#continuation-dialog').waitFor({ state: 'hidden' });
      assert.equal(requests.length, 2); assert.deepEqual(requests[0], requests[1], 'Retry changed its idempotency key');
      assert.equal(requests[0].checkpoint, spec.candidate); assert.equal(requests[0].controller_model, 'ui-test-only');
      assert.equal(requests[0].backend, 'codex'); assert.equal(requests[0].timeout_seconds, 3600);
      await page.unroute('**/api/continuations');
      await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    }
    const job = state.jobs.find(j => j.spec === activeSpec && j.report);
    if (job) {
      const report = await artifact(job.report);
      assert.ok((await page.locator('#overview').innerText()).includes(report.status), 'Report verdict missing');
      if (report.scores && /^(guarded_)?accuracy\/v1$/.test(report.scores.metric)) {
        assert.equal(await page.locator('.metric .value').first().innerText(), `${(report.scores.candidate * 100).toFixed(1)}%`);
      }
    }
    for (const evidenceId of spec.evidence || []) {
      let session;
      try { session = await artifact(evidenceId); } catch { continue; } // Transcripts may be JSONL.
      if (session.schema === 'nc/weight-agent-session/v1' && session.commitment.parent_proposal) {
        const overview = await page.locator('#overview').innerText();
        assert.ok(overview.includes(session.commitment.parent_checkpoint.slice(0, 12)), 'Inherited checkpoint missing');
        assert.ok(overview.includes(session.commitment.controller), 'Controller missing');
        assert.ok(overview.includes(`${session.changed_parameters} parameters changed`), 'Changed-value count missing');
        break;
      }
    }
    await page.getByRole('tab', { name: 'Model versions' }).click();
    assert.equal(await page.locator('#checkpoints tbody tr').count(), state.checkpoints.length);
    await page.locator('#checkpoints button').first().click();
    await page.getByText('Exact checkpoint manifest', { exact: true }).waitFor();
    assert.ok(await page.locator('#checkpoint-content tr').count() > 1, 'Tensor inventory missing');
    await page.getByRole('button', { name: 'Select version', exact: true }).click();
    const selected = await page.getByLabel('Checkpoint ID', { exact: true }).inputValue();
    await page.getByRole('button', { name: 'Run operation' }).click();
    await page.locator('#result').filter({ hasText: 'selected' }).waitFor();
    await page.locator('#selection').filter({ hasText: selected }).waitFor();
    await page.getByRole('button', { name: 'Close operations' }).click();
    const denied = await fetch(`${url}/api/actions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'select', checkpoint: selected }) });
    assert.equal(denied.status, 401);
    await page.getByRole('tab', { name: 'Evidence', exact: true }).click();
    await page.getByText('Bound acceptance policy', { exact: true }).click();
    assert.ok(await page.locator('#evaluation-evidence pre:visible').count());
    if (state.records.length) {
      await page.locator('#records > details > summary').first().click();
      await page.locator('#records').getByText('Record envelope', { exact: true }).waitFor();
    }
    await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    await page.screenshot({ path: path.join(root, '.runtime/ui-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    if (await page.locator('#experiment-picker option').count() > 1) {
      const other = await page.locator('#experiment-picker option').evaluateAll((options, active) => options.find(o => o.value !== active).value, activeSpec);
      await page.locator('#experiment-picker').selectOption(other);
      assert.notEqual(await page.locator('#experiment-picker').inputValue(), activeSpec);
      await page.locator('#experiment-picker').selectOption(activeSpec);
    }
    for (const tab of ['Overview', 'Model versions', 'Evidence', 'Controller runs']) {
      await page.getByRole('tab', { name: tab, exact: true }).click();
      const overflow = await page.evaluate(() => ({ bad: document.documentElement.scrollWidth > innerWidth, elements: [...document.querySelectorAll('#workspace *')].filter(e => e.getBoundingClientRect().right > innerWidth + 1).slice(0, 8).map(e => ({ tag: e.tagName, className: e.className, text: e.textContent.slice(0, 120) })) }));
      assert.equal(overflow.bad, false, `${tab} mobile overflow: ${JSON.stringify(overflow.elements)}`);
    }
    await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    await page.screenshot({ path: path.join(root, '.runtime/ui-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    // Missing evidence must remain unavailable; never turn it into a passing result.
    await page.route(`**/api/artifact-metadata/${spec.policy}`, route => route.fulfill({ status: 404, body: '' }));
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.locator('#overview .notice').filter({ hasText: 'Some evidence is unavailable' }).waitFor();
    await page.unroute(`**/api/artifact-metadata/${spec.policy}`);
    // Untrusted evidence remains literal text, including script-like markup.
    const patch = await artifact(spec.patch);
    await page.route(`**/api/artifact-metadata/${spec.patch}`, route => route.fulfill({ json: { ...patch, hypothesis: '<img src=x onerror="window.uiInjected=true">' } }));
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByText('<img src=x onerror="window.uiInjected=true">', { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => !!window.uiInjected), false);
    await page.unroute(`**/api/artifact-metadata/${spec.patch}`);
    // A revoked session clears prior participant data and closes its controls.
    await page.route('**/api/state', route => route.fulfill({ status: 401, body: '' }));
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'HTTP 401' }).waitFor();
    assert.equal(await page.locator('#workspace').isVisible(), false);
    assert.equal(await page.locator('#overview').innerText(), '');
    await page.unroute('**/api/state');
    await page.route('**/api/state', route => route.fulfill({ json: { jobs: [], records: [], checkpoints: [], publications: [], job_events: [], publication_events: [] } }));
    await login(); await page.getByText('No evaluation records in this participant journal.').waitFor();
    assert.equal(await page.locator('.value').count(), 0, 'Empty journal fabricated a score');
    await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
    assert.equal(await page.locator('#workspace').isVisible(), false);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(root, '.runtime/ui-check.json'), JSON.stringify({ status: 'passed', source, isolated_home: true, viewports: [[1440, 1000], [390, 844]], auth_denied: true, real_records: true, version_selection: true, unavailable_evidence: true, untrusted_text: true, revoked_session_cleared: true, empty_state: true, console_errors: errors }, null, 2));
    console.log('UI passed: real records, operations, auth, evidence failure, literal text, empty state, desktop/mobile.');
  } finally {
    if (browser) await browser.close(); server.kill('SIGINT'); await exited;
    fs.rmSync(home, { recursive: true, force: true });
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
