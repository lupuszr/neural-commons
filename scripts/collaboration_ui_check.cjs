// Read-only frontend fixtures: navigation, contribution scope and graph membership.
// Does not start model inference or contact DKG.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const root = path.resolve(__dirname, '..');
const { chromium } = require(require.resolve('@playwright/test', { paths: [path.join(root, '.runtime/dkg-source/packages/node-ui')] }));
const id = c => c.repeat(64), agent = c => '0x' + c.repeat(40);
const graph = 'workspace-graph', researchGraph = 'research-graph';
const proposal = (key, kind, author, artifact, relates_to, context_graph = graph) => ({
  id: id(key), provenance: 'fixture', record: JSON.stringify({ kind, author, artifact, relates_to, context_graph, artifacts: [], fixture: true })
});
const records = [
  proposal('3', 'PatchProposal', agent('a'), id('1'), id('8')),
  proposal('4', 'PatchProposal', agent('c'), id('2'), id('8')), // Same base, different experiment.
  proposal('5', 'Evaluation', agent('b'), id('d'), id('3')),
  proposal('6', 'Review', agent('b').toUpperCase().replace('0X', '0x'), id('e'), id('5')),
  proposal('7', 'ModelVersion', agent('e'), id('8'), null),
  proposal('9', 'Evaluation', agent('d'), id('f'), id('3'), 'other-graph'), // Unrelated graph.
];
const state = { records, jobs: [], job_events: [], checkpoints: [], publications: [], publication_events: [], selected: null };
const research = { experiments: [{
  id: 'tracked-research', sequence: 1, status: 'completed', rounds: [], events: [],
  definition: { name: 'Scoped research', model: 'Fixture LLM', objective: 'Navigation fixture.', controller: 'Test controller' }
}] };
let offline = false, browser, reads = 0;
const server = http.createServer(async (req, res) => {
  assert.equal(req.method, 'GET', 'Browsing must not cause writes');
  const pathname = new URL(req.url, 'http://fixture').pathname;
  if (pathname === '/' || pathname === '/app.js') {
    res.setHeader('Content-Type', pathname === '/' ? 'text/html' : 'text/javascript');
    return res.end(fs.readFileSync(path.join(root, 'web', pathname === '/' ? 'index.html' : 'app.js')));
  }
  res.setHeader('Content-Type', 'application/json');
  const json = data => res.end(JSON.stringify(data));
  if (['/api/continuations', '/api/shared-experiments', '/api/context-graph/collaborators'].includes(pathname)) {
    // Match the app's two read permits: initial run polling overlaps discovery.
    if (reads >= 2) { res.statusCode = 503; return json({ error: 'Read capacity occupied' }); }
    reads++; res.once('finish', () => reads--);
    await new Promise(resolve => setTimeout(resolve, pathname === '/api/continuations' ? 120 : 40));
  }
  if (pathname === '/api/ui-config') return json({ require_token: false });
  if (pathname === '/api/state') return json(state);
  if (pathname === '/api/research') return json(research);
  if (pathname === '/api/continuations') return json({ runs: [] });
  if (pathname === '/api/context-graph/collaborators') {
    if (offline) { res.statusCode = 503; return json({ error: 'Membership unavailable' }); }
    return json({ context_graph: graph, access_policy: 'public', curator: agent('a'), participants: [agent('a')], local_identity: { agentAddress: agent('a'), name: 'Workspace node' } });
  }
  if (pathname === '/api/shared-experiments') return json({ context_graph: graph, offset: 0, next_offset: null, records: [records[0], records[1]].map(row => ({ id: row.id, record: JSON.parse(row.record), downloaded: true })) });
  // A minimal report links its evaluation to the first experiment. Missing specs
  // remain visibly unavailable; contributor navigation must still work.
  if (pathname === '/api/artifact-metadata/' + id('d')) return json({ spec: id('1'), status: 'passed' });
  res.statusCode = 404; json({ error: 'Fixture has no such artifact' });
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(url + '#tracked-research');
    await page.getByRole('heading', { name: 'Scoped research', exact: true }).waitFor();
    assert.equal(await page.getByRole('tab', { name: 'Shared experiments', exact: true }).count(), 0);
    await page.getByRole('tab', { name: 'Collaborators', exact: true }).click();
    await page.getByText('No DKG collaborators have been linked to this experiment.', { exact: true }).waitFor();

    await page.getByRole('button', { name: 'Shared experiments', exact: true }).click();
    await page.locator('#graph-collaborators').getByText(/Public graph/).waitFor();
    assert.equal(await page.locator('#experiment-view').isVisible(), false);
    assert.equal(await page.locator('#shared-list article').count(), 2);
    assert.equal(await page.locator('#experiments [data-experiment]').count(), 0, 'Shared navigation must not list local experiments');
    assert.equal(await page.locator('#experiments [data-shared-record]').count(), 2);
    assert.equal(await page.locator('#experiments-heading').innerText(), 'SHARED EXPERIMENTS');
    await page.locator('#experiments [data-shared-record]').last().click();
    assert.equal(await page.locator('#experiments [aria-pressed=true]').getAttribute('data-shared-record'), id('4'));
    assert.equal(await page.locator('#experiment-view').isVisible(), false, 'Choosing a shared proposal must stay in the shared workspace');
    assert.equal(new URL(page.url()).hash, '#/shared');
    let content = await page.locator('#graph-collaborators').innerText();
    assert.match(content, /not a complete list/);
    assert(content.includes(agent('c')), 'Global graph can include another experiment author');
    assert(!content.includes(agent('d')), 'Do not mix graph identities');
    assert.equal(await page.locator('#graph-collaborators .collaborator').filter({ hasText: agent('a') }).count(), 1, 'Curator and contribution identity must be deduplicated');

    // A research update must neither leave the global view nor show its hero.
    research.experiments[0].sequence++;
    research.experiments[0].events.push({ recorded_at: '2026-11-06', event: { kind: 'note', data: { collaboration: {
      context_graph: researchGraph, summary: 'Two local participants, one controller.', participants: [
        { name: 'Participant A', address: agent('1'), roles: ['Model provider'] },
        { name: '<img src=x onerror=window.injected=true>', address: agent('2'), roles: ['Model contributor'] }
      ]
    } }, attachments: [] } });
    await page.waitForFunction(() => document.getElementById('collaborators').textContent.includes('Two local participants'));
    assert.equal(await page.locator('#experiment-view').isVisible(), false);
    await page.reload();
    await page.locator('#shared-list article').first().waitFor();
    assert.equal(await page.locator('#experiment-view').isVisible(), false, 'Deep link must restore global view');

    await page.locator('#shared-list article').first().getByRole('button', { name: 'Open experiment', exact: true }).click();
    assert.equal(await page.locator('#shared').isVisible(), false);
    assert.equal(await page.locator('#experiments [data-shared-record]').count(), 0);
    assert((await page.locator('#experiments [data-experiment]').count()) > 0);
    await page.getByRole('tab', { name: 'Collaborators', exact: true }).click();
    content = await page.locator('#collaborators').innerText();
    for (const c of ['a', 'b', 'e']) assert(content.includes(agent(c)), 'Expected linked contributor ' + c);
    for (const c of ['c', 'd']) assert(!content.includes(agent(c)), 'Unrelated contributor ' + c);
    assert.equal(await page.locator('#collaborators .collaborator').count(), 3);
    assert.match(content, /Reviewer/); assert.match(content, /Evaluator/);
    await page.goBack(); await page.locator('#shared').waitFor();
    await page.goForward(); await page.locator('#experiment-view').waitFor();
    await page.locator('[data-experiment="tracked-research"]').click();
    await page.getByRole('tab', { name: 'Collaborators', exact: true }).click();
    content = await page.locator('#collaborators').innerText();
    assert(content.includes(researchGraph)); assert(!content.includes(agent('a')));
    assert.equal(await page.locator('#collaborators img').count(), 0, 'Participant names must remain inert');
    assert.equal(await page.evaluate(() => window.injected), undefined);

    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByRole('button', { name: 'Shared experiments', exact: true }).click();
    assert.equal(await page.locator('#experiment-view').isVisible(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    offline = true;
    await page.getByRole('button', { name: 'Refresh shared experiments', exact: true }).click();
    await page.locator('#graph-collaborators').getByText(/current membership is unknown/).waitFor();
    content = await page.locator('#graph-collaborators').innerText();
    assert(!content.includes('Curator'), 'Unavailable roster must not keep stale membership roles');
    assert(content.includes(agent('a')), 'Recorded contribution remains visible');
    await page.getByRole('button', { name: 'My experiments', exact: true }).click();
    assert.equal(await page.locator('#experiment-title').innerText(), 'Scoped research');
    assert.deepEqual(errors, []);
    console.log('Collaboration UI passed: workspace navigation, mobile, deep links, history, live updates, graph scope, linked contributors, identity deduplication, public access and offline states. Fixture only.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
