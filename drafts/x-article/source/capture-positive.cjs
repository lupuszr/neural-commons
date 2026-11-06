const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'../../..'),out=path.resolve(__dirname,'..');
const {chromium}=require(require.resolve('@playwright/test',{paths:[path.join(root,'.runtime/dkg-source/packages/node-ui')]}));
(async()=>{
 const home=path.join(root,'.runtime/agnews-dkg-1/a'),listener=net.createServer();
 await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
 const server=cp.spawn(path.join(root,'target/debug/nc'),['--home',home,'serve','--port',String(port)],{stdio:'ignore'});
 const exited=new Promise(r=>server.once('exit',r));let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.goto(`http://127.0.0.1:${port}/`);await page.getByLabel('Participant access token').fill(fs.readFileSync(path.join(home,'ui.token'),'utf8').trim());
  await page.getByRole('button',{name:'Load participant'}).click();await page.getByRole('status').filter({hasText:'Loaded from'}).waitFor();
  const heading=await page.getByRole('heading',{name:'Evaluations',exact:true}).boundingBox(),jobs=await page.locator('#jobs').boundingBox();
  await page.screenshot({path:path.join(out,'assets/06-weight-evaluation.png'),fullPage:true,clip:{x:heading.x-16,y:heading.y-16,width:1172,height:jobs.y+jobs.height-heading.y+32}});
  const cards=page.locator('#records .card');const proposal=cards.filter({hasText:'PatchProposal'}).first();
  if(!(await proposal.innerText()).includes('Weight agent: codex'))throw Error('Agent provenance missing from app');
  const box=await proposal.boundingBox();await page.screenshot({path:path.join(out,'assets/07-weight-agent-proposal.png'),fullPage:true,clip:{x:box.x-8,y:box.y-8,width:box.width+16,height:box.height+16}});
  const remote=cards.filter({hasText:'remote-dkg-readback'}).filter({hasText:'Evaluation'}).first();
  if(!(await remote.innerText()).includes('passed'))throw Error('Remote acceptance missing');
  const r=await remote.boundingBox();await page.screenshot({path:path.join(out,'assets/08-weight-dkg-review.png'),fullPage:true,clip:{x:r.x-8,y:r.y-8,width:r.width+16,height:r.height+16}});
  console.log('Captured actual agent proposal, passed evaluation and DKG readback.');
 }finally{if(browser)await browser.close();server.kill('SIGINT');await exited;}
})().catch(e=>{console.error(e);process.exitCode=1});
