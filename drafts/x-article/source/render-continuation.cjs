const path=require('node:path');
const root=path.resolve(__dirname,'../../..'),out=path.resolve(__dirname,'..');
const {chromium}=require(require.resolve('@playwright/test',{paths:[path.join(root,'.runtime/dkg-source/packages/node-ui')]}));
(async()=>{const b=await chromium.launch({headless:true});try{const p=await b.newPage({viewport:{width:1600,height:900}});await p.goto('file://'+path.join(__dirname,'continuation-results.html'));await p.screenshot({path:path.join(out,'assets/10-continuation-results.png')});console.log('Rendered continuation chart');}finally{await b.close();}})();
