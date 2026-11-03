// Exercise authenticated HTTP admission/restart/cancellation with an inert worker.
// The worker never calls a controller or evaluates model weights.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..');
if(!process.argv[2])throw Error('Usage: node scripts/continuation_api_check.cjs PARTICIPANT_WITH_PASSING_PROPOSAL');
(async()=>{
 const base=fs.mkdtempSync(path.join(root,'.runtime/continuation-api-test-')),home=path.join(base,'participant'),task=path.join(base,'task');
 fs.cpSync(path.resolve(process.argv[2]),home,{recursive:true});fs.mkdirSync(task);
 for(const name of ['config','development','selection','heldout','policy','source'])fs.writeFileSync(path.join(task,name+'.json'),'{}');
 const config=JSON.parse(fs.readFileSync(path.join(home,'config.json'))),token=fs.readFileSync(config.artifact_token_file,'utf8').trim();
 const runtime=path.join(base,'inert-worker');
 fs.writeFileSync(runtime,`#!/usr/bin/python3
import sys,pathlib,json,time,os
run=pathlib.Path(sys.argv[sys.argv.index('--run')+1])
os.fstat(0)
for i in range(200):
 if (run/'cancel.json').exists(): break
 time.sleep(.05)
state=json.loads((run/'state.json').read_text());state['status']='cancelled';state['message']='Inert test worker stopped'
temp=run/'state.tmp';temp.write_text(json.dumps(state));temp.replace(run/'state.json')
`,{mode:0o700});
 const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));const url=`http://127.0.0.1:${port}`;
 let server;
 async function start(){server=cp.spawn(path.join(root,'target/debug/nc'),['--home',home,'serve','--port',String(port),'--controller-python',runtime],{stdio:'ignore'});for(let i=0;i<80;i++){try{if((await fetch(url)).ok)return;}catch{}await new Promise(r=>setTimeout(r,50));}throw Error('server did not start');}
 async function stop(){const exit=new Promise(r=>server.once('exit',r));server.kill('SIGINT');await exit;server=null;}
 const api=async(p,body,auth=true)=>fetch(url+p,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(auth?{Authorization:`Bearer ${token}`}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
 let runId;
 try{
  await start();assert.equal((await api('/api/continuations',undefined,false)).status,401);
  const state=await(await api('/api/state')).json();
  const artifact=async id=>(await api('/api/artifact-metadata/'+id)).json();
  let parent;
  for(const row of state.records){const rec=JSON.parse(row.record);if(rec.kind!=='PatchProposal')continue;const spec=await artifact(rec.artifact);const job=state.jobs.find(j=>j.spec===rec.artifact&&j.report);if(!job)continue;const report=await artifact(job.report);if(report.status==='passed'){parent={checkpoint:spec.candidate,proposal:row.id,report:job.report};break;}}
  assert.ok(parent,'Participant needs a locally evaluated passing proposal');
  runId=crypto.randomUUID();const request={id:runId,...parent,task_directory:task,backend:'codex',controller_model:'inert-test',max_rounds:4,max_probes:2,min_probes:1,max_edit_elements:8,timeout_seconds:60};
  assert.equal((await api('/api/continuations',request,false)).status,401);
  assert.equal((await api('/api/continuations',{...request,checkpoint:'0'.repeat(64)})).status,400);
  assert.equal((await api('/api/continuations',{...request,max_probes:999})).status,400);
  const admitted=await api('/api/continuations',request);assert.equal(admitted.status,200);assert.equal((await admitted.json()).id,runId);
  assert.equal((await api('/api/continuations',request)).status,200,'idempotent retry');
  assert.equal((await api('/api/continuations',{...request,controller_model:'changed'})).status,409);
  assert.equal((await api('/api/continuations',{...request,id:crypto.randomUUID()})).status,409);
  const operation=await api('/api/actions',{action:'select',checkpoint:parent.checkpoint});assert.equal(operation.status,400,'existing operations cannot overlap controller');
  await stop();await start();
  assert.equal((await api('/api/continuations',{...request,id:crypto.randomUUID()})).status,409,'server restart must preserve worker lease');
  const runs=await(await api('/api/continuations')).json();assert.equal(runs.runs.filter(r=>r.id===runId).length,1);assert.equal(runs.runs.find(r=>r.id===runId).status,'queued');
  assert.equal((await api(`/api/continuations/${runId}/cancel`,{},false)).status,401);
  assert.equal((await api(`/api/continuations/${runId}/cancel`,{})).status,200);
  let terminal=false;
  for(let i=0;i<80;i++){const r=(await(await api('/api/continuations')).json()).runs.find(r=>r.id===runId);if(r.status==='cancelled'){terminal=true;break;}await new Promise(r=>setTimeout(r,50));}
  assert.ok(terminal,'cancellation was not observed');
  assert.equal((await api(`/api/continuations/${runId}/resume`,{})).status,400,'no transcript must not resume');
  console.log('Continuation API passed: auth, exact parent, budgets, idempotency, single-flight admission, restart, cancel, resume boundary. No model call.');
 }finally{
  if(runId&&server)await api(`/api/continuations/${runId}/cancel`,{}).catch(()=>{});
  if(server)await stop();
  // Inert worker has a strict ten-second ceiling and no external effects.
  fs.rmSync(base,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e);process.exitCode=1});
