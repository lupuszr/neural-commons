// Exercise the real NC sharing endpoint against a controlled DKG adapter fixture.
// This does not grant graph access, publish, or contact a real DKG network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'nc-share-'));
  const dkgToken = crypto.randomBytes(32).toString('hex'), uiToken = crypto.randomBytes(32).toString('hex');
  const graph = '0x1234/shared-project', peer = '12D3Koo' + 'A'.repeat(45);
  const curator='0x'+'aB'.repeat(20), member='0x'+'cd'.repeat(20);
  let mode = 'ok', calls = [], child;
  const dkg = http.createServer((req, res) => {
    calls.push(req.url);
    assert(req.method === 'GET' || (req.method === 'POST' && req.url === '/api/query'), 'Discovery must not change access policy');
    assert.equal(req.headers.authorization, `Bearer ${dkgToken}`);
    res.setHeader('Content-Type', 'application/json');
    if (mode === 'denied') { res.writeHead(403); return res.end(JSON.stringify({error:'Only the graph curator can access this route'})); }
    if (req.url === '/api/query') return res.end(JSON.stringify({result:{bindings:[]}}));
    if (req.url.endsWith('/participants')) return res.end(JSON.stringify({contextGraphId:mode==='wrong-graph'?'other':graph,allowedAgents:mode==='listed'?[curator,curator.toLowerCase(),member]:[]}));
    if (req.url === '/api/context-graph/list') return res.end(JSON.stringify({contextGraphs:[{id:graph,name:'Shared project',accessPolicy:'public',curator:'did:dkg:agent:'+curator}]}));
    if (req.url.endsWith('/join-requests')) return res.end(JSON.stringify({contextGraphId:mode==='wrong-graph'?'other':graph,requests:[]}));
    if (req.url === '/api/agent/identity') return res.end(JSON.stringify({agentAddress:curator,peerId:peer,name:'Fixture node'}));
    res.writeHead(404); res.end('{}');
  });
  await new Promise(r => dkg.listen(0, '127.0.0.1', r));
  const dkgUrl = `http://127.0.0.1:${dkg.address().port}`;
  const listener = http.createServer(); await new Promise(r => listener.listen(0, '127.0.0.1', r));
  const port = listener.address().port; await new Promise(r => listener.close(r));
  try {
    fs.writeFileSync(path.join(home,'dkg.token'), dkgToken, {mode:0o600});
    fs.writeFileSync(path.join(home,'ui.token'), uiToken, {mode:0o600});
    fs.writeFileSync(path.join(home,'config.json'), JSON.stringify({dkg_url:dkgUrl,dkg_token_file:path.join(home,'dkg.token'),context_graph:graph,artifact_origin:'dkg',artifact_token_file:path.join(home,'ui.token'),require_token:true,trusted_artifact_origin:null,trusted_artifact_token_file:null}));
    fs.mkdirSync(path.join(home,'artifacts'));
    child = cp.spawn(path.join(root,'target/debug/nc'), ['--home',home,'serve','--port',String(port)], {stdio:'ignore'});
    const url = `http://127.0.0.1:${port}/api/context-graph/share`;
    for(let i=0;i<80;i++){try{await fetch(url);break;}catch{} await new Promise(r=>setTimeout(r,100));}
    assert.equal((await fetch(url)).status,401); assert.equal(calls.length,0);
    const get = async () => {const response=await fetch(url,{headers:{Authorization:`Bearer ${uiToken}`}}); assert.equal(response.status,200); return response.json();};
    let result = await get();
    assert.equal(result.invite_code,`${graph}\n${peer}`);
    assert.equal(result.dkg_url,dkgUrl);
    const catalogue=`http://127.0.0.1:${port}/api/shared-experiments`;
    assert.equal((await fetch(catalogue)).status,401);
    const headers={Authorization:`Bearer ${uiToken}`};
    const collaborators=`http://127.0.0.1:${port}/api/context-graph/collaborators`;
    assert.equal((await fetch(collaborators)).status,401);
    assert.equal((await fetch(collaborators,{headers:{Authorization:'Bearer wrong-token'}})).status,401);
    const roster=await(await fetch(collaborators,{headers})).json();
    assert.equal(roster.context_graph,graph);assert.equal(roster.access_policy,'public');
    assert.deepEqual(roster.participants,[curator.toLowerCase()]);
    assert.equal(roster.local_identity.name,'Fixture node');
    assert(!JSON.stringify(roster).includes(dkgToken));assert(!JSON.stringify(roster).includes(uiToken));
    mode='listed';assert.deepEqual((await(await fetch(collaborators,{headers})).json()).participants,[curator.toLowerCase(),member]);mode='ok';
    assert.equal((await fetch(catalogue+'?offset=100001',{headers})).status,400);
    assert.deepEqual((await (await fetch(catalogue,{headers})).json()).records,[]);
    assert(calls.includes('/api/context-graph/0x1234%2Fshared-project/join-requests'));
    assert(!JSON.stringify(result).includes(dkgToken)); assert(!JSON.stringify(result).includes(uiToken));
    for(const state of ['denied','wrong-graph']) {
      mode=state;result=await get();assert(!result.invite_code);assert.match(result.error,/Invite unavailable/);
      assert.equal((await fetch(collaborators,{headers})).status,503);
      if(state==='denied') assert.equal((await fetch(catalogue,{headers})).status,503);
    }
    await new Promise(r=>dkg.close(r));
    result=await get();assert(!result.invite_code);assert.match(result.error,/Start the configured DKG node/);
    assert.equal((await fetch(catalogue,{headers})).status,503);
    assert.equal((await fetch(collaborators,{headers})).status,503);
    console.log('Share API passed: native invite, graph roster and curator, identity deduplication, public access, authentication, graph scoping, offline handling, no credentials or DKG writes. Adapter fixture only.');
  } finally {
    if(child && child.exitCode===null){const exit=new Promise(r=>child.once('exit',r));child.kill('SIGINT');await exit;}
    if(dkg.listening) await new Promise(r=>dkg.close(r));
    fs.rmSync(home,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
