// Real UI walkthrough. Configures the creation form without starting a research
// job, then browses existing evidence and copies the workspace's native DKG invite.
// Usage: node scripts/record_workspace.cjs URL EXPERIMENT_ID TASK_DIRECTORY OUTPUT_DIRECTORY
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { performance } = require('node:perf_hooks');
const root = path.resolve(__dirname, '..');
const { chromium } = require(require.resolve('@playwright/test', { paths: [path.join(root, '.runtime/dkg-source/packages/node-ui')] }));
const [url, experiment, task, output] = process.argv.slice(2);
if (!url || !experiment || !task || !output) throw Error('Usage: node scripts/record_workspace.cjs URL EXPERIMENT_ID TASK_DIRECTORY OUTPUT_DIRECTORY');
const destination = path.resolve(output);
(async () => {
  fs.mkdirSync(destination, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  let context;
  try {
    context = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1,
      recordVideo: { dir: path.join(root, '.runtime/walkthrough-recordings'), size: { width: 1600, height: 900 } },
      permissions: ['clipboard-read', 'clipboard-write'] });
    const page = await context.newPage(), video = page.video(), started = performance.now();
    page.setDefaultTimeout(30000);
    const scenes = [], errors = [], writes = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (!['GET','HEAD'].includes(r.method())) writes.push(new URL(r.url()).pathname); });
    const hold = ms => page.waitForTimeout(ms);
    const scene = (title, subtitle) => {
      const now = (performance.now() - started) / 1000;
      if (scenes.length) scenes.at(-1).source_out = now;
      scenes.push({ title, subtitle, source_in: now }); console.log(title);
    };
    const click = async locator => {
      await locator.scrollIntoViewIfNeeded(); const box = await locator.boundingBox();
      if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 });
      await locator.click(); await hold(550);
    };
    const target = new URL(url); target.hash = encodeURIComponent(experiment);
    await page.goto(target.href); await page.locator('#workspace').waitFor();
    assert.equal(await page.locator('#experiment-picker').inputValue(), experiment);
    // A presentation cursor is the only injected layer; all app content and
    // responses remain untouched. It makes real interactions legible in the video.
    await page.evaluate(() => {
      const cursor = document.createElement('div'); cursor.id = 'recording-cursor';
      Object.assign(cursor.style, { position: 'fixed', width: '17px', height: '17px', border: '2px solid #8bdfc1', borderRadius: '50%', background: '#8bdfc133', pointerEvents: 'none', zIndex: '99999', transform: 'translate(-50%,-50%)', left: '-40px', top: '-40px' });
      document.body.append(cursor);
      document.addEventListener('mousemove', e => { cursor.style.left=e.clientX+'px'; cursor.style.top=e.clientY+'px'; });
      document.addEventListener('mousedown', () => { cursor.style.background='#8bdfc1aa'; });
      document.addEventListener('mouseup', () => { cursor.style.background='#8bdfc133'; });
    });
    scene('One workspace. Every experiment.', 'Create a run, inspect its evidence, and collaborate through OriginTrail DKG.'); await hold(2400);
    scene('01 / Set up a new experiment', 'Setup preview: choose an imported model and a prepared task folder.');
    await click(page.getByRole('button', { name: '+ New experiment', exact: true }));
    await page.waitForFunction(() => document.querySelector('#experiment-checkpoint option') && !document.getElementById('start-experiment').disabled);
    await page.getByLabel('Experiment name', { exact: true }).pressSequentially('News classification · a new experiment', { delay: 35 });
    const options = await page.locator('#experiment-checkpoint option').evaluateAll(nodes => nodes.map(n => ({ value:n.value, label:n.textContent })));
    const model = options.find(o => o.label.includes('SmolLM2') && o.label.includes('base'));
    assert(model, 'This walkthrough requires an imported SmolLM2 base for the prepared news task');
    await page.locator('#experiment-checkpoint').selectOption(model.value); await hold(1500);
    await click(page.locator('[data-browse="new-task-directory"]'));
    await page.getByLabel('Folder location', { exact: true }).fill(path.resolve(task));
    await click(page.locator('#folder-location-form').getByRole('button', { name:'Go', exact:true }));
    await page.waitForFunction(() => !document.getElementById('folder-select').disabled); await hold(1800);
    await click(page.getByRole('button', { name:'Use this folder', exact:true }));
    await page.locator('#experiment-dialog').evaluate(e=>e.scrollTop=0);
    await page.screenshot({path:path.join(root,'docs/assets/workspace-create.png')});
    scene('Your goal. Your editing scope.', 'Choose the controller and execution limits before starting the run.');
    const form=page.locator('#experiment-form');
    await form.getByLabel('Goal (optional)', {exact:true}).fill('Improve news classification while preserving the task’s regression guard.');
    await form.locator('[name=weight_scope]').scrollIntoViewIfNeeded();
    await form.locator('[name=weight_scope]').selectOption('all'); await hold(1200);
    await form.getByLabel('Controller model', {exact:true}).scrollIntoViewIfNeeded();
    await page.waitForFunction(()=>[...document.getElementById('new-controller-model').options].some(o=>o.value && o.value!=='__custom__'));
    const models=await page.locator('#new-controller-model option').evaluateAll(nodes=>nodes.map(n=>n.value).filter(v=>v && v!=='__custom__'));
    await page.locator('#new-controller-model').selectOption(models[0]); await hold(1300);
    await click(form.getByText('Execution limits', {exact:true}));
    await form.getByLabel('Maximum rounds', {exact:true}).fill('4');
    await form.getByLabel('Maximum probes', {exact:true}).fill('3');
    await form.getByLabel('Time limit (minutes)', {exact:true}).fill('15');
    await page.locator('#start-experiment').scrollIntoViewIfNeeded(); await hold(2500);
    // The create sequence is explicitly a setup preview; existing results below
    // are not presented as outputs from this unsent form.
    await click(page.getByRole('button',{name:'Close new experiment',exact:true}));
    scene('02 / Browse a recorded experiment', 'Review the actual rounds, measurements and acceptance decisions.');
    const final=page.locator('.research-round[data-round="final-evaluation"]');
    await click(final.locator(':scope > summary')); await final.scrollIntoViewIfNeeded(); await hold(4000);
    await page.screenshot({path:path.join(root,'docs/assets/workspace-results.png')});
    scene('Inspect the evidence behind the result', 'Photographs retain their recorded split, label and original file.');
    await click(page.getByRole('tab',{name:'Assets',exact:true}));
    await page.getByLabel('Asset type',{exact:true}).selectOption('image');
    await page.waitForFunction(()=>[...document.querySelectorAll('.asset-card img')].some(img=>img.naturalWidth>0)); await hold(2200);
    await click(page.locator('.asset-preview').first());
    await page.locator('#asset-detail-content img').waitFor(); await hold(2500);
    await click(page.getByRole('button',{name:'Close asset preview',exact:true}));
    await click(page.getByRole('tab',{name:'Collaborators',exact:true})); await hold(2500);
    scene('03 / Share through the workspace graph', 'Shared experiments has its own catalogue and sidebar list.');
    await click(page.getByRole('button',{name:'Shared experiments',exact:true}));
    await page.locator('#experiments [data-shared-record]').first().waitFor({timeout:90000});
    await page.locator('#graph-collaborators .collaborator').first().waitFor({timeout:90000}); await hold(2200);
    scene('Invite collaborators through DKG', 'The invite shares this graph; it does not publish an unshared local experiment.');
    await click(page.getByRole('button',{name:'Invite collaborator',exact:true}));
    await page.waitForFunction(()=>!document.getElementById('copy-share-invite').disabled); await hold(1600);
    await click(page.getByRole('button',{name:'Copy invite code',exact:true}));
    await page.locator('#share-status').filter({hasText:'Invite code copied'}).waitFor();
    await page.screenshot({path:path.join(root,'docs/assets/workspace-share-invite.png')}); await hold(2200);
    await click(page.getByRole('button',{name:'Close sharing',exact:true}));
    scene('Browse the experiments shared on this graph', 'Open downloaded evidence, or reproduce a proposal on your participant.');
    await click(page.locator('#experiments [data-shared-record]').last()); await hold(2400);
    await click(page.locator('#shared-list article').last().getByRole('button',{name:'Open experiment',exact:true}));
    await page.evaluate(()=>window.scrollTo({top:0,behavior:'smooth'})); await hold(3000);
    scenes.at(-1).source_out=(performance.now()-started)/1000;
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[], 'Walkthrough must not launch jobs or publish data');
    await page.close(); await video.saveAs(path.join(destination,'source.webm'));
    fs.writeFileSync(path.join(destination,'timeline.json'),JSON.stringify({
      title:'Neural Commons · create, inspect and share',date:'2026-11-06',
      source:'source.webm',source_dimensions:[1600,900],audio:'silent',scenes,
      provenance:'Real local Neural Commons UI recording. No API responses or experiment data were mocked.',
      scope:'Creation is a setup preview, with no submitted run. Results belong to the existing recorded experiment. Sharing copies the native invite for the configured workspace graph; it does not publish local research or change membership.'
    },null,2));
    console.log('Recorded source and timeline:',destination);
  } finally { if(context)await context.close();await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
