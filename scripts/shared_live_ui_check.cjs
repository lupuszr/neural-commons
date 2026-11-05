// Runs only against the isolated real-DKG fixture started by shared_experiments_check.py.
const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require(require.resolve('@playwright/test',{paths:[path.resolve('.runtime/dkg-source/packages/node-ui')]}));
(async()=>{
  const [url,record,output]=process.argv.slice(2);
  const browser=await chromium.launch({headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);
    await page.getByRole('tab',{name:'Shared experiments',exact:true}).click();
    const card=page.locator(`#shared-list article[data-record="${record}"]`);
    await card.getByRole('button',{name:'Download model & evidence',exact:true}).waitFor({timeout:90000});
    await card.getByRole('button',{name:'Download model & evidence',exact:true}).click();
    await page.locator('#shared-status').filter({hasText:'Download verified'}).waitFor({timeout:180000});
    const state=await (await fetch(url+'/api/state')).json();
    assert.equal(state.jobs.length,0,'Download must not execute an evaluator');
    assert(state.checkpoints.length>=2,'Downloaded models must be available locally');
    await card.getByRole('button',{name:'Reproduce & share result',exact:true}).click();
    await page.waitForFunction(()=>/Reproduction finished:|Operation did not complete successfully:/.test(document.getElementById('shared-status').textContent),{},{timeout:180000});
    assert.match(await page.locator('#shared-status').innerText(),/Reproduction finished: passed/);
    await card.getByRole('button',{name:'Open experiment',exact:true}).click();
    await page.getByRole('heading',{name:'Shared experiments',exact:true}).waitFor({state:'hidden'});
    await page.screenshot({path:path.join(output,'shared-live-reproduced.png')});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({status:'passed',discovery:true,download_without_evaluation:true,models_registered:true,reproduce_and_share:true,console_errors:errors}));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
