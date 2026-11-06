const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../../..'),out=path.resolve(__dirname,'..');
const {chromium}=require(require.resolve('@playwright/test',{paths:[path.join(root,'.runtime/dkg-source/packages/node-ui')]}));
(async()=>{const b=await chromium.launch({headless:true});try{
 const p=await b.newPage({viewport:{width:1600,height:900},deviceScaleFactor:1});
 for(const [file,png] of [['cover.html','01-cover.png'],['results.html','04-results.png']]){
  await p.goto('file://'+path.join(__dirname,file));await p.screenshot({path:path.join(out,'assets',png)});
 }
 await p.setViewportSize({width:1100,height:1000});await p.goto('file://'+path.join(out,'article.html'));
 const images=await p.locator('img').evaluateAll(xs=>xs.map(x=>({src:x.getAttribute('src'),loaded:x.complete&&x.naturalWidth>0})));
 if(images.some(x=>!x.loaded))throw Error('Missing image: '+JSON.stringify(images));
 await p.screenshot({path:path.join(out,'source/article-preview.png'),fullPage:true});
 await p.setViewportSize({width:390,height:844});
 if(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Article mobile overflow');
 console.log('PNG exports and article image/layout checks passed.');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
