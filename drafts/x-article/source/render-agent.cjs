const path=require('node:path');
const root=path.resolve(__dirname,'../../..'),out=path.resolve(__dirname,'..');
const {chromium}=require(require.resolve('@playwright/test',{paths:[path.join(root,'.runtime/dkg-source/packages/node-ui')]}));
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage({viewport:{width:1600,height:640}});
 await page.goto('file://'+path.join(__dirname,'cover-x.html'));await page.screenshot({path:path.join(out,'assets/01-cover-x.png')});
 await page.setViewportSize({width:1600,height:900});await page.goto('file://'+path.join(__dirname,'weight-results.html'));await page.screenshot({path:path.join(out,'assets/09-weight-results.png')});
 await page.setViewportSize({width:1100,height:1000});await page.goto('file://'+path.join(out,'article.html'));
 if(await page.locator('img').evaluateAll(xs=>xs.some(x=>!x.complete||!x.naturalWidth)))throw Error('Missing article image');
 await page.screenshot({path:path.join(out,'source/article-preview.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 console.log('Article images and layout verified.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
