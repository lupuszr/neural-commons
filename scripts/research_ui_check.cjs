// Exercise real journal writes, managed execution, restart recovery and UI polling.
// Uses a disposable participant; no model inference, DKG writes or account access.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const net = require('node:net');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const {chromium} = require(require.resolve('@playwright/test', {paths:[path.join(root,'.runtime/dkg-source/packages/node-ui')]}));
const home = fs.mkdtempSync(path.join(root,'.runtime/research-ui-test-'));
const binary = path.join(root,'target/debug/nc');
const nc = args => cp.execFileSync(binary,['--home',home,...args],{encoding:'utf8'});
const write = (name, data) => { const file=path.join(home,name);fs.writeFileSync(file,JSON.stringify(data));return file; };
let serial=0;
function record(kind,data,round,attachments=[]) {
  return nc(['research','record',write(`event-${++serial}.json`,{id:`event-${serial}`,experiment:'tracked-test',...(round?{round}:{}),kind,data,attachments})]);
}
let server,browser,worker;
async function start(port) {
  server=cp.spawn(binary,['--home',home,'serve','--port',String(port)],{stdio:'ignore'});
  for(let i=0;i<80;i++) {
    try {if((await fetch(`http://127.0.0.1:${port}/api/research`)).ok)return;} catch {}
    await new Promise(r=>setTimeout(r,100));
  }
  throw Error('Server did not start');
}
async function stop() {
  const p=server;server=null;if(!p || p.exitCode!==null)return;
  await new Promise(resolve=>{p.once('exit',resolve);p.kill('SIGINT');});
}
(async()=>{
  nc(['put',write('test-input.json',{fixture:true})]);
  write('config.json',{dkg_url:'http://127.0.0.1:1',dkg_token_file:path.join(home,'unused'),context_graph:'test',artifact_origin:'http://127.0.0.1',require_token:false,artifact_token_file:path.join(home,'unused'),trusted_artifact_origin:null,trusted_artifact_token_file:null});
  const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
  try {
    await start(port); const url=`http://127.0.0.1:${port}`;
    browser=await chromium.launch({headless:true});
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);await page.locator('#workspace').waitFor();
    record('experiment',{name:'Tracked experiment',model:'Test LLM',objective:'Check registration before work.',scope:'Test fixture only.'});
    await page.getByRole('button',{name:/Tracked experiment/}).waitFor({timeout:15000});
    await page.getByRole('button',{name:/Tracked experiment/}).click();
    await page.getByText('Experiment registered. No numerical rounds have started.').waitFor();
    const event=write('managed.json',{id:'managed-start',experiment:'tracked-test',round:'probe-1',kind:'round',data:{label:'First numerical round',kind:'probe',hypothesis:'Record before execution, survive a UI restart.'}});
    const feedback=path.join(home,'feedback.json');
    // The child asserts its start is already durable before it does any work.
    const code=`import sqlite3,time,json; c=sqlite3.connect(${JSON.stringify(path.join(home,'journal.sqlite'))}); assert c.execute("select count(*) from research_events where id='managed-start'").fetchone()[0]==1; time.sleep(12); json.dump({'correct':3,'n':4},open(${JSON.stringify(feedback)},'w'))`;
    worker=cp.spawn(binary,['--home',home,'research','run',event,'--result',feedback,'--','python3','-c',code],{stdio:'ignore'});
    const completed=new Promise(resolve=>worker.once('exit',resolve));
    await page.locator('.research-round').filter({hasText:'First numerical round'}).getByText('Running',{exact:true}).waitFor({timeout:10000});
    await stop();await start(port);
    const live=await(await fetch(url+'/api/research')).json();
    assert.equal(live.experiments[0].rounds[0].status,'running','Server restart must not interrupt a live numerical worker');
    assert.equal(await completed,0);
    await page.locator('.research-round').getByText('Awaiting review',{exact:true}).waitFor({timeout:15000});
    const checkpoint=(name,values)=>{
      let header=Buffer.from(JSON.stringify({'model.text_model.layers.0.weight':{dtype:'F32',shape:[1],data_offsets:[0,4]},'model.vision_model.layers.0.weight':{dtype:'F32',shape:[1],data_offsets:[4,8]}}));
      while(header.length%8)header=Buffer.concat([header,Buffer.from(' ')]);
      const size=Buffer.alloc(8);size.writeBigUInt64LE(BigInt(header.length));const data=Buffer.alloc(8);values.forEach((v,i)=>data.writeFloatLE(v,i*4));
      const file=path.join(home,name+'.safetensors');fs.writeFileSync(file,Buffer.concat([size,header,data]));
      return JSON.parse(nc(['register',file])).checkpoint;
    };
    const base=checkpoint('base',[1,2]),candidate=checkpoint('candidate',[1,3]);
    record('result',{status:'completed',summary:'Measured on selection only.',measurements:[{label:'Camera accuracy',split:'selection',parent_correct:2,correct:3,total:4}],changed_tensors:['model.layer.weight'],checkpoints:[{label:'Test candidate',checkpoint:candidate,parent_checkpoint:base,sha256:'test fixture'}]},'probe-1');
    record('decision',{verdict:'not_selected',reason:'Selection gain requires a separate final evaluation.'},'probe-1');
    await page.getByText('Not selected',{exact:true}).waitFor({timeout:15000});
    assert.match(await page.locator('#overview').innerText(),/3\/4 · 75.0%/);
    assert.match(await page.locator('#overview').innerText(),/Not run/);
    assert.match(await page.locator('#overview').innerText(),/selection/);
    await page.getByRole('button',{name:'Inspect Test candidate',exact:true}).click();
    await page.locator('#checkpoint-content').getByRole('heading',{name:'Weight changes',exact:true}).waitFor();
    assert.match(await page.locator('#checkpoint-content').innerText(),/model.vision_model.layers.0.weight/);
    await page.locator('#checkpoint-content').getByRole('button',{name:/^Language layer 0/}).waitFor();
    await page.locator('#checkpoint-content').getByRole('button',{name:/^Vision layer 0/}).waitFor();
    await page.getByRole('button',{name:'Close checkpoint details',exact:true}).click();
    await page.reload();await page.getByRole('heading',{name:'Tracked experiment',exact:true}).waitFor();
    await page.getByText('Not selected',{exact:true}).waitFor();
    assert.equal(new URL(page.url()).hash,'#tracked-test');
    // Serve a real raster through the authenticated artifact path, not a local URL.
    const photo=path.join(home,'sample.png');
    const photoBytes=await page.screenshot({path:photo,clip:{x:0,y:0,width:4,height:4}});
    const photoHash=require('node:crypto').createHash('sha256').update(photoBytes).digest('hex');
    const html=path.join(home,'untrusted.html');fs.writeFileSync(html,'<script>window.attachmentExecuted=true</script><h1>Attached HTML stays text</h1>');
    const files=Array.from({length:14},(_,i)=>({label:`support-${i}.json`,path:write(`support-${i}.json`,{evidence:i})}));
    record('note',{description:{summary:'A readable experiment description.',method:'Direct internal weight edits.',dataset:'A UI test fixture.',limitations:['No scientific result.'],sources:[{label:'Unsafe source',url:'javascript:alert(1)'}]},assets:[{artifact:photoHash,label:'sample.png',filename:'sample.png',kind:'image',split:'development',target_label:'normal',caption:'A tiny fixture image.'}]},undefined,[{label:'sample.png',path:photo},{label:'untrusted.html',path:html},...files]);
    record('note',{summary:'The same photo also belongs to this round.'},'probe-1',[{label:'Duplicate photo.png',path:photo}]);
    await page.getByRole('tab',{name:'Description',exact:true}).click();
    await page.getByText('A readable experiment description.',{exact:true}).waitFor({timeout:15000});
    assert.equal(await page.getByRole('link',{name:'Unsafe source'}).count(),0);
    await page.getByRole('tab',{name:'Assets',exact:true}).click();
    assert.match(await page.locator('#assets').innerText(),/^Experiment assets\s+1 image ·/);
    assert.equal(await page.locator('.asset-card').count(),12,'First asset page must be bounded');
    await page.locator('.asset-pagination').getByRole('button',{name:'Next',exact:true}).click();
    assert.match(await page.locator('.asset-pagination').innerText(),/Page 2/);
    await page.getByLabel('Asset type',{exact:true}).selectOption('image');
    assert.equal(await page.locator('.asset-card').count(),1,'The same content must not appear twice');
    await page.locator('.asset-card img').waitFor({state:'visible'});
    assert.equal(await page.locator('.asset-card img').evaluate(img=>img.naturalWidth),4);
    await page.getByLabel('Data split',{exact:true}).selectOption('development');
    await page.getByRole('button',{name:'Preview sample.png',exact:true}).click();
    await page.locator('#asset-detail-content img').waitFor({state:'visible'});
    const downloadPromise=page.waitForEvent('download');
    await page.locator('#asset-detail-dialog').getByRole('button',{name:'Download',exact:true}).click();
    const download=await downloadPromise;assert.equal(download.suggestedFilename(),'sample.png');
    assert.deepEqual(fs.readFileSync(await download.path()),photoBytes,'Download must preserve original file bytes');
    await page.getByRole('button',{name:'Close asset preview',exact:true}).click();
    await page.getByLabel('Data split',{exact:true}).selectOption('all');
    await page.getByLabel('Asset type',{exact:true}).selectOption('document');
    await page.getByLabel('Search assets',{exact:true}).fill('untrusted');
    await page.getByRole('button',{name:'Preview untrusted.html',exact:true}).click();
    await page.locator('#asset-detail-content > pre').waitFor();
    assert.match(await page.locator('#asset-detail-content > pre').innerText(),/Attached HTML stays text/);
    assert.equal(await page.evaluate(()=>window.attachmentExecuted),undefined,'An attached HTML file must never execute');
    await page.getByRole('button',{name:'Close asset preview',exact:true}).click();
    await page.getByLabel('Search assets',{exact:true}).fill('does-not-exist');
    await page.getByText('No assets match these filters.',{exact:true}).waitFor();
    await page.getByLabel('Search assets',{exact:true}).fill('');
    await page.getByLabel('Asset type',{exact:true}).selectOption('image');
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Mobile layout overflows');
    await page.screenshot({path:path.join(root,'.runtime/research-ui-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1440,height:1000});
    await page.screenshot({path:path.join(root,'.runtime/research-ui-desktop.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    const state=await(await fetch(url+'/api/research')).json();
    assert.equal(state.experiments[0].events.length,7);
    assert.equal((await fetch(url+'/api/research',{headers:{Origin:'http://foreign.invalid'}})).status,401);
    assert.equal((await fetch(url+'/api/artifact-metadata/'+photoHash,{headers:{Origin:'http://foreign.invalid'}})).status,401);
    console.log(JSON.stringify({passed:true,checks:['register-before-command','automatic-appearance','running-worker','server-restart','automatic-result','decision-and-metric-splits','reload-and-deep-link','description','asset-pagination-and-filters','immutable-photo-download','raster-preview-under-csp','inert-html-preview','asset-deduplication','mobile','origin-auth'],home}));
  } finally {
    if(worker && worker.exitCode===null)worker.kill('SIGTERM');
    if(browser)await browser.close();await stop();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
