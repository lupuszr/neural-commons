const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'../../..');
const out=path.resolve(__dirname,'..');
const {chromium}=require(require.resolve('@playwright/test',{paths:[path.join(root,'.runtime/dkg-source/packages/node-ui')]}));
async function capture(browser,relativeHome,tokenFile,kind){
 const home=path.join(root,relativeHome), listener=net.createServer();
 await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
 const log=fs.openSync(path.join(out,'source',kind+'-capture.log'),'w');
 const server=cp.spawn(path.join(root,'target/debug/nc'),['--home',home,'serve','--port',String(port)],{stdio:['ignore',log,log]});
 const exited=new Promise(r=>server.once('exit',r));
 let page;
 try{
  for(let i=0;i<80;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.getByLabel('Participant access token').fill(fs.readFileSync(path.join(home,tokenFile),'utf8').trim());
  await page.getByRole('button',{name:'Load participant'}).click();
  await page.getByRole('status').filter({hasText:'Loaded from'}).waitFor();
  // Read-only captures of actual rendered records. No content or styling changes.
  if(kind==='iris'){
   const heading=await page.getByRole('heading',{name:'Evaluations',exact:true}).boundingBox();
   const jobs=await page.locator('#jobs').boundingBox();
   await page.screenshot({fullPage:true,path:path.join(out,'assets/02-app-evaluations.png'),clip:{x:heading.x-20,y:heading.y-20,width:1172,height:jobs.y+jobs.height-heading.y+40}});
   const iris=page.locator('#records .card').filter({hasText:'accuracy/v1'}).first();
   if(await iris.count()!==1)throw Error('Iris evidence card missing');
  }else{
   const cards=page.locator('#records .card');
   const details=await cards.evaluateAll(xs=>xs.map((x,i)=>({i,text:x.innerText.slice(0,240),top:x.offsetTop,height:x.offsetHeight})));
   fs.writeFileSync(path.join(out,'source/cross-host-card-index.json'),JSON.stringify(details,null,2));
   const heading=await page.getByRole('heading',{name:'Collaboration & lineage',exact:true}).boundingBox();
   const first=await cards.first().boundingBox();
   await page.screenshot({fullPage:true,path:path.join(out,'assets/05-regression-rejected.png'),clip:{x:heading.x-16,y:heading.y-16,width:1164,height:first.y+first.height-heading.y+24}});
   const review=cards.filter({hasText:'remote-dkg-readback'}).filter({hasText:'passed'}).first();
   const positive=await review.boundingBox();
   await page.screenshot({fullPage:true,path:path.join(out,'assets/03-dkg-lineage.png'),clip:{x:positive.x-8,y:positive.y-8,width:2*positive.width+32,height:positive.height+16}});
  }
 }finally{if(page)await page.close();server.kill('SIGINT');await exited;fs.closeSync(log);}
}
(async()=>{const browser=await chromium.launch({headless:true});try{await capture(browser,'.runtime/demo-20261103-091624/a','artifact.token','iris');await capture(browser,'.runtime/cross-host-20261103-122714/participant','ui.token','cross-host');}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
