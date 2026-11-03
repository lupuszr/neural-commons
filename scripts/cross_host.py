#!/usr/bin/env python3
"""Two physical host validation. HTTP coordinates test steps; artifacts use DKG only."""
import argparse,hashlib,json,os,pathlib,queue,secrets,signal,socket,struct,subprocess,sys,threading,time,urllib.request,urllib.error
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

def main():
 p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--root',type=pathlib.Path);p.add_argument('--bind',default='192.168.1.236');p.add_argument('--peer',default='192.168.1.237');p.add_argument('--port',type=int,default=18762);a=p.parse_args()
 root=(a.root or pathlib.Path(__file__).resolve().parents[1]).resolve();sys.path.insert(0,str(root/'scripts'))
 if a.worker:
  node=sorted((pathlib.Path.home()/'.nvm/versions/node').glob('v24.*/bin/node'))[-1]
  os.environ['PATH']=str(node.parent)+':'+os.environ['PATH']
  os.environ.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='url.https://github.com/OriginTrail/dkg.git.insteadOf',GIT_CONFIG_VALUE_0='git@github.com:OriginTrail/dkg-v9.git',GIT_TERMINAL_PROMPT='0')
 import dkg_runtime as d,local_chain
 run=root/'.runtime'/('cross-host-'+time.strftime('%Y%m%d-%H%M%S'));run.mkdir(mode=0o700)
 processes=[];logs=[];home=run/'participant';dh=run/'dkg';home.mkdir(mode=0o700)
 binary=root/'target/debug/nc'
 def log(name):f=open(run/name,'w');logs.append(f);return f
 def nc(*args):
  r=subprocess.run([str(binary),'--home',str(home),*args],cwd=root,text=True,capture_output=True,timeout=600)
  if r.returncode:raise RuntimeError(r.stderr[-4000:])
  return json.loads(r.stdout)
 def free():
  with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
 def retry(fn,seconds=120):
  until=time.monotonic()+seconds;last=None
  while time.monotonic()<until:
   try:return fn()
   except Exception as e:last=e;time.sleep(1)
  raise RuntimeError(str(last))
 def configure(cg):
  (home/'config.json').write_text(json.dumps({'dkg_url':f'http://127.0.0.1:{api}','dkg_token_file':str(dh/'agent.token'),'context_graph':cg,'artifact_origin':'dkg','artifact_token_file':str(home/'ui.token'),'trusted_artifact_origin':None,'trusted_artifact_token_file':None}))
  (home/'ui.token').write_text(secrets.token_hex(32));os.chmod(home/'ui.token',0o600)
 def artifact_proof(record):
  fetched=retry(lambda:nc('fetch',record));cp=json.loads((home/'artifacts'/fetched['artifact']).read_text());blob=home/'artifacts'/cp['artifact']
  import hashlib
  h=hashlib.sha256()
  with blob.open('rb') as f:
   for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
  assert h.hexdigest()==cp['artifact']
  return {'record':fetched,'bytes':blob.stat().st_size,'sha256':h.hexdigest(),'path':str(blob)}
 api=free();peerport=free();d.setup_network()
 evidence={'schema':'nc/cross-host-validation/v1','status':'running','host':socket.gethostname(),'run':str(run),'checks':{}}
 server=None
 try:
  subprocess.run(['git','fetch','origin','testnet-canary'],cwd=d.SOURCE,check=True,capture_output=True,timeout=60)
  sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=d.SOURCE,text=True).strip();latest=subprocess.check_output(['git','rev-parse','origin/testnet-canary'],cwd=d.SOURCE,text=True).strip();assert sha==latest,'Rebuild latest canary before test'
  evidence['dkg_source']=sha
  if a.worker:
   base=a.worker
   def get(path):
    with urllib.request.urlopen(base+path,timeout=30) as r:return json.load(r)
   def post(body):
    with urllib.request.urlopen(urllib.request.Request(base+'/result',json.dumps(body).encode(),{'Content-Type':'application/json'}),timeout=30) as r:r.read()
   cfg=get('/config');assert cfg['dkg_source']==sha
   binary=run/'nc'
   with urllib.request.urlopen(base+'/runtime/nc',timeout=60) as r:binary.write_bytes(r.read())
   assert hashlib.sha256(binary.read_bytes()).hexdigest()==cfg['binary_sha256'];binary.chmod(0o755)
   evidence['binary_sha256']=cfg['binary_sha256']
   d.config(dh,api,peerport,202,cfg['chain']);local_chain.fund(dh,cfg['chain'],cfg['token'])
   proc=d.launch(dh,log('dkg.log'));processes.append(proc);ident=d.wait_ready(dh,api,proc)
   assert not (home/'artifacts').exists()
   post({'id':'ready','value':{'identity':ident,'host':socket.gethostname(),'run':str(run),'peerport':peerport,'dkg_source':sha,'empty_artifacts':True}})
   deadline=time.monotonic()+1800
   while time.monotonic()<deadline:
    job=get('/job')
    if not job:time.sleep(1);continue
    try:
     op=job['op']
     if op=='connect':
      cg=job['cg'];configure(cg);d.request(dh,api,'/api/connect',{'multiaddr':job['multiaddr']},admin=True);retry(lambda:d.request(dh,api,'/api/context-graph/subscribe',{'contextGraphId':cg}));value={'subscribed':True}
     elif op=='reproduce':value=retry(lambda:nc('reproduce',job['record']))
     elif op=='fetch':value=retry(lambda:nc('fetch',job['record']))
     elif op=='large':value=artifact_proof(job['record'])
     elif op=='restart':
      os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=30);proc=d.launch(dh,log('dkg-restarted.log'));processes.append(proc);restored=d.wait_ready(dh,api,proc);assert restored['agentAddress']==ident['agentAddress'];d.request(dh,api,'/api/connect',{'multiaddr':job['multiaddr']},admin=True)
      home=run/'fresh-reader';home.mkdir(mode=0o700);configure(cg);value=artifact_proof(job['record']);value['same_identity']=True
     elif op=='stop':post({'id':job['id'],'value':{'stopped':True}});break
     else:raise ValueError(op)
     post({'id':job['id'],'value':value})
    except Exception as e:post({'id':job['id'],'error':str(e)})
   evidence['status']='passed'
  else:
   jobs=queue.Queue();results={};lock=threading.Condition();chain,token=local_chain.start(run,free(),processes,log)
   remote_chain={**chain,'rpcUrl':f'http://{a.bind}:{a.port}/rpc','rpcUrls':[f'http://{a.bind}:{a.port}/rpc'],'walletRpcUrls':[f'http://{a.bind}:{a.port}/rpc']}
   class H(BaseHTTPRequestHandler):
    def allowed(self):return self.client_address[0]==a.peer
    def send(self,value):
     b=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
     if not self.allowed():self.send_error(403);return
     if self.path=='/worker.py':
      b=pathlib.Path(__file__).read_bytes();self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
     elif self.path=='/runtime/nc':
      b=binary.read_bytes();self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
     elif self.path=='/config':self.send({'chain':remote_chain,'token':token,'dkg_source':sha,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()})
     elif self.path=='/job':
      try:self.send(jobs.get_nowait())
      except queue.Empty:self.send(None)
     else:self.send_error(404)
    def do_POST(self):
     if not self.allowed():self.send_error(403);return
     n=int(self.headers.get('Content-Length',0))
     if n>1048576:self.send_error(413);return
     body=self.rfile.read(n)
     if self.path=='/rpc':
      req=urllib.request.Request(chain['rpcUrl'],body,{'Content-Type':'application/json'})
      with urllib.request.urlopen(req,timeout=30) as r:response=json.load(r)
      self.send(response)
     elif self.path=='/result':
      r=json.loads(body)
      with lock:results[r['id']]=r;lock.notify_all()
      self.send({'ok':True})
     else:self.send_error(404)
    def log_message(self,*args):pass
   server=ThreadingHTTPServer((a.bind,a.port),H);threading.Thread(target=server.serve_forever,daemon=True).start()
   def await_result(key,timeout=600):
    with lock:
     if not lock.wait_for(lambda:key in results,timeout):raise RuntimeError('Remote deadline: '+key)
     r=results.pop(key)
    if 'error' in r:raise RuntimeError('Remote: '+r['error'])
    return r['value']
   def remote(op,**kw):
    key=secrets.token_hex(8);jobs.put({'id':key,'op':op,**kw});return await_result(key)
   d.config(dh,api,peerport,201,chain);local_chain.fund(dh,chain,token);proc=d.launch(dh,log('dkg.log'));processes.append(proc);ident=d.wait_ready(dh,api,proc)
   print('READY_FOR_MAC_MINI',run,flush=True)
   other=await_result('ready',900);evidence['remote']=other;evidence['identity']=ident;assert ident['agentAddress']!=other['identity']['agentAddress'];assert other['host']!=evidence['host'];assert other['empty_artifacts']
   cg=ident['agentAddress'].lower()+'/nc-cross-host-'+secrets.token_hex(6);configure(cg);evidence['context_graph']=cg
   d.request(dh,api,'/api/context-graph/create',{'id':cg,'name':'Neural Commons two physical machines','accessPolicy':0,'publishPolicy':1,'register':True})
   multi=f'/ip4/{a.bind}/tcp/{peerport}/p2p/{ident["peerId"]}'
   remote('connect',cg=cg,multiaddr=multi);fixture=nc('fixture')
   for label,expected in [('repair','passed'),('regression','failed')]:
    spec=fixture['candidates'][label]['spec'];local=nc('evaluate',spec);proposal=nc('propose',spec,'--fixture');repro=remote('reproduce',record=proposal['record']);assert local['evaluation']['status']==repro['evaluation']['status']==expected
    for metric in ['base_mse','candidate_mse']:assert local['evaluation'][metric]==repro['evaluation'][metric]
    readback=retry(lambda:nc('fetch',repro['publication']['record']));assert readback['author']==other['identity']['agentAddress'];assert readback['relates_to']==proposal['record']
    review=retry(lambda:nc('fetch',repro['review']['record']));assert review['kind']=='Review'
    for related in proposal['related_records']:remote('fetch',record=related['record'])
    again=remote('reproduce',record=proposal['record']);assert again['report']==repro['report']
    evidence['checks'][label]={'a':local,'proposal':proposal,'b':repro,'a_readback':readback,'review':review,'duplicate_reused':True};print(label,expected,flush=True)
   large=run/'large.safetensors';count=24*1024*1024;header=json.dumps({'large.weights':{'dtype':'F32','shape':[count],'data_offsets':[0,count*4]}},separators=(',',':')).encode()
   with large.open('wb') as f:
    f.write(struct.pack('<Q',len(header)));f.write(header)
    for _ in range(96):f.write(struct.pack('<f',.125)*262144)
   cp=nc('register',str(large))['checkpoint'];published=nc('publish-checkpoint',cp,'--fixture');proof=remote('large',record=published['record']);assert proof['bytes']==large.stat().st_size
   evidence['checks']['large_dkg_artifact']=proof;print('96 MiB transferred and verified',flush=True)
   cold=remote('restart',multiaddr=multi,record=published['record']);assert cold['sha256']==proof['sha256'];evidence['checks']['remote_cold_restart']=cold;print('Mac mini cold restart and fresh cache passed',flush=True)
   remote('stop');evidence['status']='passed'
 except BaseException as e:evidence['status']='failed';evidence['error']=str(e);raise
 finally:
  for proc in processes:
   if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
  for proc in processes:
   try:proc.wait(timeout=15)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
  if server:server.shutdown()
  for f in logs:f.close()
  (run/'validation.json').write_text(json.dumps(evidence,indent=2));print('Validation:',run/'validation.json',flush=True)
if __name__=='__main__':main()
