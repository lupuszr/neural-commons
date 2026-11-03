// Local browser QA against the actual read-only application and a completed demo.
const fs=require('node:fs');const path=require('node:path');const cp=require('node:child_process');const net=require('node:net');
const root=path.resolve(__dirname,'..');const home=path.resolve(process.argv[2]);
const {chromium}=require(require.resolve('@playwright/test',{paths:[path.join(root,'.runtime/dkg-source/packages/node-ui')]}));
(async()=>{
 const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
 const log=fs.openSync(path.join(root,'.runtime/ui-server.log'),'w');
 const server=cp.spawn(path.join(root,'target/debug/nc'),['--home',home,'serve','--port',String(port)],{stdio:['ignore',log,log]});
 let browser;
 try{
  for(let i=0;i<50;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.getByLabel('Participant access token').fill('wrong-token');await page.getByRole('button',{name:'Load participant'}).click();await page.getByRole('status').filter({hasText:'HTTP 401'}).waitFor();
  await page.getByLabel('Participant access token').fill(fs.readFileSync(path.join(home,'artifact.token'),'utf8').trim());await page.getByRole('button',{name:'Load participant'}).click();await page.getByRole('status').filter({hasText:'Loaded from'}).waitFor();
  if(await page.locator('#checkpoints .card').count()<2)throw Error('checkpoint data missing');
  if(await page.locator('#jobs .card').count()<2)throw Error('evaluation data missing');
  if(!await page.locator('#jobs').getByText('passed',{exact:true}).count() || !await page.locator('#jobs').getByText('failed',{exact:true}).count())throw Error('behavioral verdict missing');
  const state=JSON.parse(cp.execFileSync(path.join(root,'target/debug/nc'),['--home',home,'state'],{encoding:'utf8'}));
  const selected=state.checkpoints[0].id;
  await page.getByLabel('Operation').selectOption('select');
  await page.getByLabel('Checkpoint ID',{exact:true}).fill(selected);
  await page.getByRole('button',{name:'Run operation'}).click();
  await page.locator('#result').filter({hasText:'selected'}).waitFor();
  await page.locator('#selection').filter({hasText:selected}).waitFor();
  const denied=await fetch(`http://127.0.0.1:${port}/api/actions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'select',checkpoint:selected})});
  if(denied.status!==401)throw Error('unauthenticated mutation was accepted');
  await page.screenshot({path:path.join(root,'.runtime/ui-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'.runtime/ui-mobile.png'),fullPage:true});
  const overflow=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,width:document.documentElement.scrollWidth,viewport:innerWidth,elements:Array.from(document.querySelectorAll('body *')).filter(e=>e.scrollWidth>e.clientWidth+1 || e.getBoundingClientRect().right>innerWidth).slice(0,8).map(e=>({tag:e.tagName,id:e.id,width:e.clientWidth,scroll:e.scrollWidth,whiteSpace:getComputedStyle(e).whiteSpace,wrap:getComputedStyle(e).overflowWrap}))}));if(overflow.overflow)throw Error('mobile horizontal overflow: '+JSON.stringify(overflow));
  if(errors.length)throw Error(errors.join('\n'));
  fs.writeFileSync(path.join(root,'.runtime/ui-check.json'),JSON.stringify({status:'passed',source:home,viewports:[[1440,1000],[390,844]],auth_denied:true,real_records:true,version_selection:true,unauthenticated_mutation_rejected:true,console_errors:errors},null,2));
  console.log('UI passed: authentication, actual records, desktop/mobile layout, no JavaScript errors');
 }finally{if(browser)await browser.close();server.kill('SIGINT');await new Promise(r=>server.once('exit',r));fs.closeSync(log);}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
