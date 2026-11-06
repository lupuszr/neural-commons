// Browser regression checks against a copy of a completed participant journal.
// No DKG services, evaluator processes or external writes are started.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const net = require('node:net');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
if (!process.argv[2]) throw Error('Usage: node scripts/ui_check.cjs PARTICIPANT_HOME');
const source = path.resolve(process.argv[2]);
const requireToken = !process.argv.includes('--local');
const { chromium } = require(require.resolve('@playwright/test', { paths: [path.join(root, '.runtime/dkg-source/packages/node-ui')] }));
(async () => {
  const home = fs.mkdtempSync(path.join(root, '.runtime/ui-test-'));
  fs.cpSync(source, home, { recursive: true });
  const config = JSON.parse(fs.readFileSync(path.join(home, 'config.json'), 'utf8'));
  const token = fs.readFileSync(config.artifact_token_file, 'utf8').trim();
  if (!requireToken) { delete config.require_token; config.artifact_token_file = path.join(home, 'missing-token-file'); fs.writeFileSync(path.join(home, 'config.json'), JSON.stringify(config)); }
  const listener = net.createServer(); await new Promise(r => listener.listen(0, '127.0.0.1', r));
  const port = listener.address().port; await new Promise(r => listener.close(r));
  const server = cp.spawn(path.join(root, 'target/debug/nc'), ['--home', home, 'serve', ...(requireToken ? ['--require-token'] : []), '--port', String(port)], { stdio: 'ignore' });
  const exited = new Promise(r => server.once('exit', r));
  let browser;
  try {
    const url = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 80; i++) { try { if ((await fetch(url)).ok) break; } catch {} await new Promise(r => setTimeout(r, 100)); }
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route(/\/api\/controller-models\?/, route => {
      const backend=new URL(route.request().url()).searchParams.get('backend');
      return route.fulfill({json:{models:[{id:`fixture-${backend}`,name:`Fixture ${backend}`}],message:'Fixture catalog'}});
    });
    async function customModel(form,value){
      await form.locator('[name=controller_model]').selectOption('__custom__');
      await form.getByLabel('Custom model ID',{exact:true}).fill(value);
    }
    await page.goto(url);
    async function login(value = token) {
      await page.getByLabel('Participant access token').fill(value);
      await page.getByRole('button', { name: 'Load participant' }).click();
    }
    if (requireToken) {
      await login('wrong-token');
      await page.getByRole('status').filter({ hasText: 'HTTP 401' }).waitFor();
      assert.equal(await page.locator('#workspace').isVisible(), false);
      await login();
    } await page.getByRole('status').filter({ hasText: 'Loaded from' }).waitFor();
    const state = await (await fetch(`${url}/api/state`, { headers: { Authorization: `Bearer ${token}` } })).json();
    assert.ok(state.jobs.length || state.records.length, 'Use a completed participant journal');
    assert.ok(await page.locator('.experiment').count(), 'No experiments rendered');
    assert.equal(await page.getByLabel('Participant access token').inputValue(), '', 'Token retained in field');
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0, 'Token persisted');
    const activeSpec = await page.locator('.experiment[aria-pressed=true]').getAttribute('data-experiment');
    const artifact = async id => (await fetch(`${url}/api/artifact-metadata/${id}`, { headers: { Authorization: `Bearer ${token}` } })).json();
    const spec = await artifact(activeSpec);
    // Native DKG sharing, with no network membership mutation in browser QA.
    const graph='fixture/shared-graph', peer='12D3Koo'+'A'.repeat(45);
    await page.route('**/api/context-graph/collaborators',route=>route.fulfill({json:{context_graph:graph,access_policy:'public',participants:[]}}));
    let shareAvailable=true;
    await page.route('**/api/context-graph/share',route=>route.fulfill({json:shareAvailable?
      {context_graph:graph,dkg_url:'http://127.0.0.1:9999',invite_code:`${graph}\n${peer}`}:
      {context_graph:graph,dkg_url:'http://127.0.0.1:9999',error:'Invite unavailable. Start the configured DKG node.'}}));
    await page.context().grantPermissions(['clipboard-read','clipboard-write']);
    await page.getByRole('button',{name:'Invite collaborator',exact:true}).click();
    await page.locator('#share-status').filter({hasText:'Ready to copy'}).waitFor();
    assert.equal(await page.getByLabel('DKG invite code',{exact:true}).inputValue(),`${graph}\n${peer}`);
    await page.getByRole('button',{name:'Copy invite code',exact:true}).click();
    await page.locator('#share-status').filter({hasText:'Invite code copied'}).waitFor();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),`${graph}\n${peer}`);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.locator('#share-dialog').evaluate(e=>e.scrollWidth<=e.clientWidth+1),true);
    await page.screenshot({path:path.join(root,'.runtime/ui-share-context-graph.png')});
    await page.setViewportSize({width:1440,height:1000});
    shareAvailable=false;
    await page.getByRole('button',{name:'Refresh invite',exact:true}).click();
    await page.locator('#share-status').filter({hasText:'Invite unavailable'}).waitFor();
    assert.equal(await page.locator('#copy-share-invite').isDisabled(),true);
    assert.equal(await page.locator('#share-invite').inputValue(),'');
    await page.getByRole('button',{name:'Close sharing',exact:true}).click();
    await page.unroute('**/api/context-graph/share');
    const sharedRecord = state.records.map(row=>({...row,data:JSON.parse(row.record)})).find(row=>row.data.kind==='PatchProposal' && row.data.artifact===activeSpec);
    if(sharedRecord) {
      let downloaded=false, offline=false; const sharedActions=[];
      await page.route('**/api/shared-experiments?*',route=>{
        const offset=Number(new URL(route.request().url()).searchParams.get('offset'));
        return route.fulfill({status:offline?503:200,json:offline?{error:'DKG test unavailable'}:{context_graph:graph,offset,next_offset:offset===0?20:null,records:offset===0?[{id:sharedRecord.id,record:sharedRecord.data,downloaded}]:[]}});
      });
      await page.route('**/api/actions',route=>{
        const body=route.request().postDataJSON();sharedActions.push(body);downloaded=true;
        return route.fulfill({json:body.action==='fetch'?sharedRecord.data:{evaluation:{status:'passed'}}});
      });
      await page.getByRole('button',{name:'Shared experiments',exact:true}).click();
      const card=page.locator('#shared-list article');
      await card.getByRole('button',{name:'Download model & evidence',exact:true}).waitFor();
      assert.equal(sharedActions.length,0,'Discovery must not download or evaluate');
      await card.getByRole('button',{name:'Download model & evidence',exact:true}).click();
      await page.locator('#shared-status').filter({hasText:'Download verified'}).waitFor();
      assert.deepEqual(sharedActions[0],{action:'fetch',record:sharedRecord.id});
      await card.getByRole('button',{name:'Reproduce & share result',exact:true}).click();
      await page.locator('#shared-status').filter({hasText:'Reproduction finished: passed'}).waitFor();
      assert.equal(sharedActions[1].action,'reproduce');
      await page.screenshot({path:path.join(root,'.runtime/ui-shared-experiments.png')});
      await page.getByRole('button',{name:'Next page',exact:true}).click();
      await page.locator('#shared-status').filter({hasText:'No shared proposals'}).waitFor();
      await page.getByRole('button',{name:'Previous page',exact:true}).click();
      await card.waitFor();
      offline=true;
      await page.getByRole('button',{name:'Refresh shared experiments',exact:true}).click();
      await page.locator('#shared-status').filter({hasText:'Shared experiments unavailable'}).waitFor();
      assert.equal(await card.count(),0,'Unavailable graph must clear stale actionable cards');
      await page.unroute('**/api/actions'); await page.unroute('**/api/shared-experiments?*');
      await page.getByRole('button',{name:'My experiments',exact:true}).click();
      await page.getByRole('tab',{name:'Overview',exact:true}).click();
    }
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
      await page.locator('#continuation-form').getByLabel('Goal (optional)').fill('Improve the inherited model');
      await customModel(page.locator('#continuation-form'),'ui-test-only');
      await page.screenshot({ path: path.join(root, '.runtime/ui-continuation-form.png'), fullPage: true });
      await page.getByRole('button', { name: 'Start controller', exact: true }).click();
      await page.locator('#continuation-error').filter({ hasText: 'retry this request safely' }).waitFor();
      await page.getByRole('button', { name: 'Start controller', exact: true }).click();
      await page.locator('#continuation-dialog').waitFor({ state: 'hidden' });
      assert.equal(requests.length, 2); assert.deepEqual(requests[0], requests[1], 'Retry changed its idempotency key');
      assert.equal(requests[0].checkpoint, spec.candidate); assert.equal(requests[0].controller_model, 'ui-test-only');
      assert.equal(requests[0].backend, 'codex'); assert.equal(requests[0].timeout_seconds, 3600);
      assert.deepEqual(requests[0].weight_scope,{mode:'all'});
      assert.equal(requests[0].objective,'Improve the inherited model');
      assert.equal(requests[0].max_edit_elements,null);
      await page.unroute('**/api/continuations');
      await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    }
    // New experiment: real controls, captured admission, no paid controller call.
    const freshRequests = [];
    await page.route('**/api/experiments', async route => {
      const body = route.request().postDataJSON(); freshRequests.push(body);
      await route.fulfill({ status: freshRequests.length === 1 ? 503 : 200,
        json: freshRequests.length === 1 ? { error: 'Retry test' } : { id: body.id, status: 'queued' } });
    });
    await page.getByRole('button', { name: '+ New experiment', exact: true }).click();
    const form = page.locator('#experiment-form');
    await page.waitForFunction(() => !document.getElementById('start-experiment').disabled);
    const startingModel = await form.getByLabel('Starting model').inputValue();
    const startingManifest = await artifact(startingModel);
    assert.ok(['model_config','tokenizer','tokenizer_config','special_tokens'].every(k=>startingManifest.inference_artifacts?.[k]), 'Starting model must have its inference bundle');
    if (await form.locator(`option[value="${spec.base}"]`).count()) assert.equal(startingModel, spec.base);
    await form.getByLabel('Experiment name').fill('New UI experiment');
    await form.getByLabel('Prepared task folder').fill('/inert/prepared-task');
    await form.getByLabel('Goal (optional)').fill('Improve classification');
    assert.equal(await form.getByLabel('Editable weights').inputValue(),'all');
    await form.getByLabel('Controller model',{exact:true}).selectOption('fixture-codex');
    await form.getByLabel('Editable weights').selectOption('selected');
    await form.getByRole('button',{name:'Start experiment',exact:true}).click();
    await page.locator('#experiment-error').filter({hasText:'Select at least one editable tensor'}).waitFor();
    assert.equal(freshRequests.length,0,'An empty tensor selection must not submit');
    await form.getByLabel('Find tensors').fill('layers.0.');
    const selectedTensor='model.layers.0.mlp.down_proj.weight';
    await form.getByRole('checkbox',{name:selectedTensor,exact:true}).check();
    await form.getByLabel('Additional instructions (optional)').fill('Prefer sparse edits');
    await form.getByLabel('Controller model',{exact:true}).selectOption('fixture-codex');
    await form.getByLabel('Controller backend').selectOption('openai');
    await page.waitForFunction(()=>document.querySelector('#experiment-form [name=controller_model] option[value="fixture-openai"]'));
    assert.equal(await form.getByLabel('Controller model',{exact:true}).inputValue(),'');
    await form.getByLabel('Controller model',{exact:true}).selectOption('fixture-openai');
    await form.getByLabel('Controller backend').selectOption('codex');
    await page.waitForFunction(()=>document.querySelector('#experiment-form [name=controller_model] option[value="fixture-codex"]'));
    await customModel(form,'inert-controller');
    const taskFolder=path.join(home,'task-ready');fs.mkdirSync(taskFolder);
    for(const name of ['config','development','selection','heldout','policy','source'])fs.writeFileSync(path.join(taskFolder,name+'.json'),'{}');
    await form.getByLabel('Prepared task folder').fill(home);
    await form.locator('[data-browse="new-task-directory"]').click();
    await page.getByRole('button',{name:'Open folder task-ready',exact:true}).waitFor();
    assert.equal(await page.locator('#folder-select').isDisabled(),true);
    await page.getByRole('button',{name:'Open folder task-ready',exact:true}).click();
    await page.waitForFunction(()=>!document.getElementById('folder-select').disabled);
    await page.screenshot({path:path.join(root,'.runtime/ui-folder-chooser.png')});
    await page.locator('#folder-select').click();
    assert.equal(await form.getByLabel('Prepared task folder').inputValue(),taskFolder);
    await form.locator('[data-browse="new-task-directory"]').click();
    await page.locator('#folder-dialog').getByRole('button',{name:'Cancel',exact:true}).click();
    assert.equal(await form.getByLabel('Prepared task folder').inputValue(),taskFolder);
    await form.getByLabel('Prepared task folder').fill('/inert/prepared-task');
    await page.screenshot({ path: path.join(root, '.runtime/ui-new-experiment.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.locator('#experiment-dialog').evaluate(e => e.scrollWidth <= e.clientWidth + 1), true);
    await page.screenshot({ path: path.join(root, '.runtime/ui-new-experiment-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await form.getByRole('button', { name: 'Start experiment', exact: true }).click();
    await page.locator('#experiment-error').filter({ hasText: 'retry this request safely' }).waitFor();
    await form.getByRole('button', { name: 'Start experiment', exact: true }).click();
    await page.locator('#experiment-dialog').waitFor({ state: 'hidden' });
    assert.deepEqual(freshRequests[0], freshRequests[1]);
    assert.equal(freshRequests[0].name, 'New UI experiment');
    assert.equal(freshRequests[0].objective, 'Improve classification');
    assert.deepEqual(freshRequests[0].weight_scope,{mode:'selected',tensors:['model.layers.0.mlp.down_proj.weight']});
    assert.equal(freshRequests[0].instructions,'Prefer sparse edits');
    assert.equal(freshRequests[0].max_edit_elements,null);
    assert.equal(freshRequests[0].checkpoint, startingModel);
    assert.equal(freshRequests[0].proposal, undefined);
    assert.equal(freshRequests[0].report, undefined);
    await page.unroute('**/api/experiments');
    await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    // Import a real tiny Safetensors fixture through the dedicated model UI.
    const modelFolder = path.join(home, 'ui-import-model'); fs.mkdirSync(modelFolder);
    const header = Buffer.from(JSON.stringify({weight:{dtype:'F32',shape:[1],data_offsets:[0,4]}}));
    const prefix = Buffer.alloc(8); prefix.writeBigUInt64LE(BigInt(header.length));
    const tensor = Buffer.alloc(4); tensor.writeFloatLE(1);
    fs.writeFileSync(path.join(modelFolder,'model.safetensors'),Buffer.concat([prefix,header,tensor]));
    for(const filename of ['config.json','tokenizer.json','tokenizer_config.json']) fs.writeFileSync(path.join(modelFolder,filename),'{}');
    await page.getByRole('button', {name:'+ New experiment',exact:true}).click();
    await page.waitForFunction(()=>!document.getElementById('start-experiment').disabled);
    await page.getByRole('button', {name:'Import another model'}).click();
    const importDialog = page.locator('#import-model-dialog');
    await importDialog.getByRole('heading',{name:'Import model',exact:true}).waitFor();
    assert.equal(await page.locator('#operation-dialog').isVisible(),false);
    await importDialog.getByRole('button',{name:'Back to experiment',exact:true}).click();
    assert.equal(await form.getByLabel('Experiment name').inputValue(),'New UI experiment');
    await page.getByRole('button', {name:'Import another model'}).click();
    await importDialog.getByLabel('Local model folder').fill(home);
    await importDialog.getByRole('button',{name:'Import model',exact:true}).click();
    await page.locator('#import-model-error').filter({hasText:'Model folder is missing'}).waitFor();
    await importDialog.getByLabel('Local model folder').fill(modelFolder);
    await page.screenshot({path:path.join(root,'.runtime/ui-import-model-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await importDialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1),true);
    await page.screenshot({path:path.join(root,'.runtime/ui-import-model-mobile.png')});
    await page.setViewportSize({width:1440,height:1000});
    await importDialog.getByRole('button',{name:'Import model',exact:true}).click();
    await page.getByRole('status').filter({hasText:'Imported ui-import-model'}).waitFor();
    assert.equal(await page.locator('#experiment-dialog').isVisible(),true);
    assert.equal(await form.getByLabel('Experiment name').inputValue(),'New UI experiment');
    assert.equal(await form.getByLabel('Prepared task folder').inputValue(),'/inert/prepared-task');
    assert.equal(await form.getByLabel('Goal (optional)').inputValue(),'Improve classification');
    assert.ok((await page.locator('#experiment-checkpoint option:checked').innerText()).includes('ui-import-model'));
    const imported=await artifact(await form.getByLabel('Starting model').inputValue());
    for(const key of ['model_config','tokenizer','tokenizer_config','special_tokens']) assert.ok(imported.inference_artifacts[key]);
    await page.getByRole('button',{name:'Close new experiment',exact:true}).click();
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
    assert.equal(await page.locator('#checkpoints tbody tr').count(), state.checkpoints.length + 1);
    await page.locator('#checkpoints tr').filter({hasText: spec.candidate.slice(0,12)}).getByRole('button',{name:'Inspect ↗'}).click();
    await page.getByText('Exact checkpoint manifest', { exact: true }).waitFor();
    const map=page.getByRole('region',{name:'Checkpoint tensor map'});
    await map.waitFor();
    const manifest=await artifact(spec.candidate);
    const changes=await (await fetch(`${url}/api/checkpoint-diff?base=${spec.base}&candidate=${spec.candidate}`,{headers:{Authorization:`Bearer ${token}`}})).json();
    assert.ok(changes.changed>0);assert.equal(changes.changes.length,Math.min(100,changes.changed));
    assert.ok(await map.locator('.weights-changed').count()>0,'Changed groups must be marked');
    assert.ok((await map.innerText()).includes(changes.changed.toLocaleString()));
    const values=page.getByRole('region',{name:'Changed weight values'});
    assert.ok((await values.innerText()).includes(String(changes.changes[0].before)));
    if(changes.has_more){await values.getByRole('button',{name:'Next',exact:true}).click();await values.getByText(`101–200 of ${changes.changed.toLocaleString()} changed values.`,{exact:false}).waitFor();await values.getByRole('button',{name:'Previous',exact:true}).click();await values.getByText(`1–100 of ${changes.changed.toLocaleString()} changed values.`,{exact:false}).waitFor();}
    await page.getByLabel('Changed tensors only',{exact:true}).uncheck();
    const total=manifest.tensors.reduce((sum,t)=>sum+t.shape.reduce((n,d)=>n*d,1),0);
    assert.ok((await map.innerText()).includes(new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(total)));
    const layer=map.getByRole('button',{name:/^Layer 0 /});
    if(await layer.count()){
      await layer.click();
      const rows=await page.locator('#checkpoint-content .tensor-table tbody tr').count();
      assert.equal(rows,manifest.tensors.filter(t=>/(?:^|\.)layers\.0\./.test(t.name)).length);
      await map.getByRole('button',{name:'Show all',exact:true}).click();
      assert.equal(await page.locator('#checkpoint-content .tensor-table tbody tr').count(),manifest.tensors.length);
    }
    await page.screenshot({path:path.join(root,'.runtime/ui-checkpoint-diff.png')});

    assert.ok(await page.locator('#checkpoint-content tr').count() > 1, 'Tensor inventory missing');
    await page.getByRole('button', { name: 'Select version', exact: true }).click();
    const selected = await page.getByLabel('Checkpoint ID', { exact: true }).inputValue();
    await page.getByRole('button', { name: 'Run operation' }).click();
    await page.locator('#result').filter({ hasText: 'selected' }).waitFor();
    await page.locator('#selection').filter({ hasText: selected }).waitFor();
    await page.getByRole('button', { name: 'Close operations' }).click();
    const denied = await fetch(`${url}/api/actions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'select', checkpoint: selected }) });
    assert.equal(denied.status, requireToken ? 401 : 200);
    if (!requireToken) {
      assert.equal(await page.locator('#connection').isVisible(), false);
      assert.equal(await page.locator('#disconnect').isVisible(), false);
      for (const headers of [{Origin:'https://foreign.example'}, {Origin:'null'}, {Host:`rebound.example:${port}`}, {'Sec-Fetch-Site':'cross-site'}]) {
        // Use raw HTTP: fetch may normalize Host and Sec-Fetch-* headers.
        const status = await new Promise((resolve, reject) => {
          const req = http.request(`${url}/api/actions`, { method:'POST', headers:{'Content-Type':'application/json',...headers} }, response => { response.resume(); resolve(response.statusCode); });
          req.on('error', reject); req.end(JSON.stringify({action:'select',checkpoint:selected}));
        });
        assert.equal(status,401,`Foreign request must be rejected: ${JSON.stringify(headers)}`);
      }
    }
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
    for (const tab of ['Overview', 'Collaborators', 'Model versions', 'Evidence', 'Controller runs']) {
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
    if (requireToken) await login(); else await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByText('No evaluation records in this participant journal.').waitFor();
    assert.equal(await page.locator('.value').count(), 0, 'Empty journal fabricated a score');
    if (requireToken) {
      await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
      assert.equal(await page.locator('#workspace').isVisible(), false);
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(root, '.runtime/ui-check.json'), JSON.stringify({ status: 'passed', source, isolated_home: true, viewports: [[1440, 1000], [390, 844]], require_token: requireToken, auth_denied: requireToken, real_records: true, version_selection: true, unavailable_evidence: true, untrusted_text: true, revoked_session_cleared: true, empty_state: true, console_errors: errors }, null, 2));
    console.log(`Mode: ${requireToken ? 'token required' : 'local automatic'}`);
    console.log('UI passed: real records, operations, auth, evidence failure, literal text, empty state, desktop/mobile.');
  } finally {
    if (browser) await browser.close(); server.kill('SIGINT'); await exited;
    fs.rmSync(home, { recursive: true, force: true });
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
