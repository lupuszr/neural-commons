// Record a real two-participant import. A keeps its existing workspace; B must
// start with an empty, separate NC workspace on a second, already subscribed DKG
// node. No fixture responses, direct store copies or simulated progress.
// Usage: node scripts/record_shared_split.cjs SESSION.json PROPOSAL_ID OUTPUT_DIR
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { performance } = require('node:perf_hooks');
const root = path.resolve(__dirname, '..');
const { chromium } = require(require.resolve('@playwright/test', { paths: [path.join(root, '.runtime/dkg-source/packages/node-ui')] }));
const [sessionFile, proposal, output] = process.argv.slice(2);
if (!sessionFile || !proposal || !output) throw Error('Usage: node scripts/record_shared_split.cjs SESSION.json PROPOSAL_ID OUTPUT_DIR');
const session = JSON.parse(fs.readFileSync(sessionFile)), destination = path.resolve(output);
const api = async (base, route) => { const response = await fetch(base + route); assert(response.ok, `${route}: ${response.status}`); return response.json(); };
(async () => {
  assert(!fs.existsSync(destination) || fs.readdirSync(destination).length === 0, 'Choose a new output directory to preserve existing recordings');
  fs.mkdirSync(destination, { recursive: true });
  const before = await api(session.url, '/api/state');
  assert.equal(before.records.length, 0); assert.equal(before.checkpoints.length, 0); assert.equal(before.jobs.length, 0);
  const catalogue = await api(session.participant_a_url, '/api/shared-experiments?offset=0');
  const item = catalogue.records.find(row => row.id === proposal); assert(item && item.downloaded);
  const spec = await api(session.participant_a_url, '/api/artifact-metadata/' + item.record.artifact);
  const bGraph = await api(session.url, '/api/context-graph/collaborators');
  const aGraph = await api(session.participant_a_url, '/api/context-graph/collaborators');
  assert.equal(aGraph.context_graph, bGraph.context_graph);
  assert.notEqual(aGraph.local_identity.agentAddress.toLowerCase(), bGraph.local_identity.agentAddress.toLowerCase());
  const browser = await chromium.launch({ headless: true });
  let ca, cb;
  try {
    ca = await browser.newContext({ viewport: { width: 1600, height: 900 }, recordVideo: { dir: path.join(root, '.runtime/split-recordings'), size: { width: 1600, height: 900 } }, permissions: ['clipboard-read', 'clipboard-write'] });
    const a = await ca.newPage(), aClock = performance.now(), aVideo = a.video();
    cb = await browser.newContext({ viewport: { width: 940, height: 900 }, recordVideo: { dir: path.join(root, '.runtime/split-recordings'), size: { width: 940, height: 900 } } });
    const b = await cb.newPage(), bClock = performance.now(), bVideo = b.video();
    const errors = [], writes = [], scenes = [], actions = [];
    for (const [page, actor] of [[a,'A'],[b,'B']]) {
      page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(actor + ': ' + error.message));
      page.on('request', request => { if (!['GET','HEAD'].includes(request.method())) writes.push({actor,path:new URL(request.url()).pathname,body:request.postDataJSON()}); });
    }
    const hold = ms => new Promise(resolve => setTimeout(resolve, ms));
    const mark = (title, subtitle, layout) => {
      const now = performance.now();
      if (scenes.length) { scenes.at(-1).a_out=(now-aClock)/1000; scenes.at(-1).b_out=(now-bClock)/1000; }
      scenes.push({title,subtitle,layout,a_in:(now-aClock)/1000,b_in:(now-bClock)/1000}); console.log(title);
    };
    const click = async locator => { await locator.click(); await hold(450); };
    await Promise.all([a.goto(session.participant_a_url+'/#/shared'),b.goto(session.url)]);
    await Promise.all([a.locator('#shared-list article').first().waitFor(),b.locator('#workspace').waitFor()]);
    await a.locator('#graph-collaborators .collaborator').first().waitFor();
    mark('Share the workspace graph', 'A copies a native DKG invite for the graph containing this SmolLM2 experiment.', 'single');
    await click(a.getByRole('button',{name:'Invite collaborator',exact:true}));
    await a.waitForFunction(()=>!document.getElementById('copy-share-invite').disabled); await hold(1500);
    await click(a.getByRole('button',{name:'Copy invite code',exact:true}));
    await a.locator('#share-status').filter({hasText:'Invite code copied'}).waitFor(); await hold(1700);
    const invite=await a.locator('#share-invite').inputValue();assert(invite.startsWith(catalogue.context_graph+'\n'));
    // Actual responsive reflow at the split point, not a horizontally compressed UI.
    // Playwright keeps the A capture canvas at 1600px; the narrow page occupies
    // its top-left 940px, which the editor crops without stretching.
    await a.setViewportSize({width:940,height:900}); await hold(250);
    mark('A shares. B adds the experiment.', 'Two separate workspaces on two local DKG nodes. B starts with no imported models.', 'split');
    await Promise.all([
      click(a.getByRole('button',{name:'Close sharing',exact:true})),
      click(b.getByRole('button',{name:'Shared experiments',exact:true}))
    ]);
    const cardA=a.locator(`#shared-list article[data-record="${proposal}"]`), cardB=b.locator(`#shared-list article[data-record="${proposal}"]`);
    await cardB.getByRole('button',{name:'Download model & evidence',exact:true}).waitFor({timeout:90000});
    await Promise.all([
      click(a.locator(`#experiments [data-shared-record="${proposal}"]`)),
      click(b.locator(`#experiments [data-shared-record="${proposal}"]`))
    ]);
    await hold(1800);
    mark('A reviews evidence while B imports', 'B retrieves the shared model and evidence through DKG; A continues in its own workspace.', 'split');
    const downloadStart=performance.now();
    actions.push({actor:'B',action:'fetch',record:proposal});
    await Promise.all([
      click(cardB.getByRole('button',{name:'Download model & evidence',exact:true})),
      click(cardA.getByRole('button',{name:'Open experiment',exact:true}))
    ]);
    let imported;
    await Promise.all([
      (async()=>{
        await a.evaluate(()=>window.scrollTo({top:0,behavior:'smooth'}));await hold(2000);
        await click(a.getByRole('tab',{name:'Evidence',exact:true}));await hold(1600);
        await click(a.getByRole('tab',{name:'Collaborators',exact:true}));await hold(2300);
        await click(a.getByRole('tab',{name:'Overview',exact:true}));await hold(1800);
      })(),
      (async()=>{
        await b.waitForFunction(()=>/Download verified|Operation did not complete/.test(document.getElementById('shared-status').textContent),null,{timeout:180000});
        assert.match(await b.locator('#shared-status').innerText(),/Download verified/);
        imported=await api(session.url,'/api/state');
        assert.equal(imported.jobs.length,0,'Downloading must not invent an evaluation');
        assert(imported.checkpoints.some(cp=>cp.id===spec.base));assert(imported.checkpoints.some(cp=>cp.id===spec.candidate));
        assert(imported.records.some(row=>row.id===proposal));
        console.log('B verified model import in',((performance.now()-downloadStart)/1000).toFixed(2),'seconds');
        await hold(1900);
        await click(cardB.getByRole('button',{name:'Open experiment',exact:true}));
        await b.evaluate(()=>window.scrollTo({top:0,behavior:'smooth'}));await hold(1700);
        await click(b.locator('#overview .checkpoint.candidate'));
        await b.locator('#checkpoint-content').getByRole('heading',{name:'Weight changes',exact:true}).waitFor({timeout:90000});
        await hold(2400);
      })()
    ]);
    mark('The same checkpoint. Independent workspaces.', 'A keeps its recorded evaluation. B inspects the exact imported weight changes.', 'split');
    await Promise.all([
      (async()=>{await click(a.locator('#overview .checkpoint.candidate'));await a.locator('#checkpoint-content').getByRole('heading',{name:'Weight changes',exact:true}).waitFor();})(),
      (async()=>{await b.locator('#checkpoint-content').getByRole('button',{name:/^Embeddings/}).first().click();await hold(600);})()
    ]);
    await hold(3400);
    await Promise.all([a.getByRole('button',{name:'Close checkpoint details',exact:true}).click(),b.getByRole('button',{name:'Close checkpoint details',exact:true}).click()]);
    await Promise.all([a.evaluate(()=>window.scrollTo({top:0,behavior:'smooth'})),b.evaluate(()=>window.scrollTo({top:0,behavior:'smooth'}))]);
    await hold(2200);
    const ended=performance.now();scenes.at(-1).a_out=(ended-aClock)/1000;scenes.at(-1).b_out=(ended-bClock)/1000;
    assert.deepEqual(errors,[]);
    assert.deepEqual(writes,[{actor:'B',path:'/api/actions',body:{action:'fetch',record:proposal}}]);
    await Promise.all([a.screenshot({path:path.join(destination,'participant-a.png')}),b.screenshot({path:path.join(destination,'participant-b.png')})]);
    await Promise.all([a.close(),b.close()]);
    await Promise.all([aVideo.saveAs(path.join(destination,'participant-a.webm')),bVideo.saveAs(path.join(destination,'participant-b.webm'))]);
    fs.writeFileSync(path.join(destination,'split-timeline.json'),JSON.stringify({
      date:new Date().toISOString().slice(0,10),scenes,sources:{a:'participant-a.webm',b:'participant-b.webm'},a_canvas:[1600,900],split_viewport:[940,900],audio:'silent',
      actors:{a:{agent_address:aGraph.local_identity.agentAddress},b:{agent_address:bGraph.local_identity.agentAddress}},
      context_graph:catalogue.context_graph,proposal,spec:item.record.artifact,base_checkpoint:spec.base,candidate_checkpoint:spec.candidate,
      before:{records:before.records.length,checkpoints:before.checkpoints.length,jobs:before.jobs.length},
      after:{records:imported.records.length,checkpoints:imported.checkpoints.length,jobs:imported.jobs.length},actions,
      scope:'Two local DKG nodes and separate NC workspaces, controlled by one assistant for a UI demonstration. B was already subscribed to the public graph; the recorded new action is adding the model and evidence to an empty local workspace. No new evaluation or model improvement is claimed. The preceding photo-study tour is separate from this shared SmolLM2 experiment.',
      runtime_note:'Uses the existing local DKG deployment; this UI recording does not qualify a new runtime revision.'
    },null,2));
    console.log('Recorded real two-participant import:',destination);
  } finally {if(ca)await ca.close();if(cb)await cb.close();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
