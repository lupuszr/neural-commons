#!/usr/bin/env python3
"""One-command, separate-process collaboration demo. Always tears down its children."""
import local_chain
import argparse, json, os, pathlib, secrets, signal, socket, sqlite3, subprocess, time, urllib.request
from dkg_runtime import ROOT, SOURCE, config, setup_network, launch, wait_ready, request

def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def main():
    args=argparse.ArgumentParser();args.add_argument('--run-dir',type=pathlib.Path);opts=args.parse_args()
    run=(opts.run_dir or ROOT/'.runtime'/('demo-'+time.strftime('%Y%m%d-%H%M%S'))).resolve()
    run.mkdir(parents=True,exist_ok=False);os.chmod(run,0o700)
    evidence={'schema':'nc/demo-validation/v1','status':'running','chain':'disposable local Hardhat EVM; no public-chain publication','transport':'real DKG daemons and libp2p','run':str(run),'checks':{}}
    processes=[];logs=[];dkg_processes=[]
    def log_for(path):f=open(path,'w');logs.append(f);return f
    def nc(home,*args,timeout=300):
        r=subprocess.run([str(ROOT/'target/debug/nc'),'--home',str(home),*args],cwd=ROOT,text=True,capture_output=True,timeout=timeout)
        if r.returncode:raise RuntimeError(f'nc {args[0]}: {r.stderr[-3000:]}')
        return json.loads(r.stdout)
    def eventually(fn,seconds=45):
        until=time.monotonic()+seconds;last=None
        while time.monotonic()<until:
            try:return fn()
            except (RuntimeError,OSError) as e:last=e;time.sleep(.5)
        raise RuntimeError(f'readback deadline exceeded: {last}')
    try:
        subprocess.run(['git','fetch','origin','testnet-canary'],cwd=SOURCE,check=True,capture_output=True)
        current=subprocess.check_output(['git','rev-parse','origin/testnet-canary'],cwd=SOURCE,text=True).strip()
        built=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()
        if built!=current:raise RuntimeError('DKG latest canary changed; run scripts/setup.py to rebuild the fetched revision')
        evidence['dkg_source']=built
        setup_network()
        chain,chain_token=local_chain.start(run,port(),processes,log_for)
        evidence['local_chain']=chain
        homes=[run/'a',run/'b'];dkg_homes=[run/'dkg-a',run/'dkg-b'];apis=[port(),port()];peers=[port(),port()];artports=[port(),port()];identities=[]
        cg_suffix='nc-demo-'+secrets.token_hex(8)
        for i in range(2):
            config(dkg_homes[i],apis[i],peers[i],i+101,chain)
            local_chain.fund(dkg_homes[i],chain,chain_token)
            p=launch(dkg_homes[i],log_for(run/f'dkg-{i}.log'));processes.append(p);dkg_processes.append(p)
            identities.append(wait_ready(dkg_homes[i],apis[i],p))
            homes[i].mkdir();os.chmod(homes[i],0o700)
            token=homes[i]/'artifact.token';token.write_text(secrets.token_hex(32));os.chmod(token,0o600)
        assert identities[0]['agentAddress']!=identities[1]['agentAddress']
        evidence['identities']=identities
        cg=identities[0]['agentAddress'].lower()+'/'+cg_suffix
        evidence['context_graph']=cg
        request(dkg_homes[1],apis[1],'/api/connect',{'multiaddr':f'/ip4/127.0.0.1/tcp/{peers[0]}/p2p/{identities[0]["peerId"]}'},admin=True)
        request(dkg_homes[0],apis[0],'/api/context-graph/create',{'id':cg,'name':'Neural Commons controlled repair','accessPolicy':0,'publishPolicy':1,'register':True})
        eventually(lambda:request(dkg_homes[1],apis[1],'/api/context-graph/subscribe',{'contextGraphId':cg}))
        for i in range(2):
            cfg={'dkg_url':f'http://127.0.0.1:{apis[i]}','dkg_token_file':str(dkg_homes[i]/'agent.token'),'context_graph':cg,'artifact_origin':'dkg','artifact_token_file':str(homes[i]/'artifact.token'),'trusted_artifact_origin':None,'trusted_artifact_token_file':None}
            (homes[i]/'config.json').write_text(json.dumps(cfg,indent=2))
        fixture=nc(homes[0],'fixture');evidence['fixture']=fixture
        # Initialize B's durable journal while leaving its artifact store empty.
        db=sqlite3.connect(homes[1]/'journal.sqlite');db.close()
        assert not (homes[1]/'artifacts').exists() or not list((homes[1]/'artifacts').iterdir())
        evidence['checks']['b_started_without_artifacts']=True
        evidence['artifact_transport']='DKG native imported artifact protocol; no peer HTTP artifact credentials'
        evidence['dkg_source_patch']=subprocess.check_output(['git','diff'],cwd=SOURCE,text=True)
        time.sleep(2)
        for label in ['repair','regression']:
            spec=fixture['candidates'][label]['spec']
            local=nc(homes[0],'evaluate',spec)
            expected='passed' if label=='repair' else 'failed'
            assert local['evaluation']['status']==expected,local
            proposal=nc(homes[0],'propose',spec,'--fixture')
            (run/f'{label}-proposal.json').write_text(json.dumps(proposal,indent=2))
            reproduction=eventually(lambda:nc(homes[1],'reproduce',proposal['record']))
            assert reproduction['evaluation']['status']==expected,reproduction
            assert reproduction['evaluation']['process_id']!=local['evaluation']['process_id']
            assert reproduction['evaluation']['base_mse']==local['evaluation']['base_mse']
            assert reproduction['evaluation']['candidate_mse']==local['evaluation']['candidate_mse']
            readback=eventually(lambda:nc(homes[0],'fetch',reproduction['publication']['record']))
            assert readback['author']==identities[1]['agentAddress']
            assert readback['relates_to']==proposal['record']
            review=eventually(lambda:nc(homes[0],'fetch',reproduction['review']['record']))
            assert review['kind']=='Review' and review['relates_to']==reproduction['publication']['record']
            for related in proposal['related_records']:
                eventually(lambda:nc(homes[1],'fetch',related['record']))
            again=nc(homes[1],'reproduce',proposal['record'])
            assert again['report']==reproduction['report']
            assert again['publication']['record']==reproduction['publication']['record']
            evidence['checks'][label]={'a':local,'proposal':proposal,'b':reproduction,'a_readback':readback,'duplicate_reused':True}
            print(label,expected,'with B reproduction and A readback',flush=True)
        from iris_experiment import experiment, configure
        iris=experiment(homes[0],run/'iris')
        configure(homes[1])
        proposal=nc(homes[0],'propose',iris['spec'])
        reproduction=eventually(lambda:nc(homes[1],'reproduce',proposal['record']),90)
        assert reproduction['evaluation']['scores']==iris['evaluation']['evaluation']['scores']
        assert reproduction['evaluation']['status']==iris['evaluation']['evaluation']['status']
        assert reproduction['evaluation']['status'] in ['passed','failed'],reproduction
        assert reproduction['evaluation']['process_id']!=iris['evaluation']['evaluation']['process_id']
        readback=eventually(lambda:nc(homes[0],'fetch',reproduction['publication']['record']))
        assert not readback['fixture']
        evidence['checks']['iris_external_evaluator']={'a':iris,'b':reproduction,'a_readback':readback,'proposal':proposal}
        print('Real Iris classifier evaluated and reproduced through DKG',flush=True)
        # A checkpoint larger than the old ceiling travels only through DKG.
        import struct,hashlib
        large=run/'large.safetensors'
        count=24*1024*1024
        header=json.dumps({'large.weights':{'dtype':'F32','shape':[count],'data_offsets':[0,count*4]}},separators=(',',':')).encode()
        with open(large,'wb') as f:
            f.write(struct.pack('<Q',len(header)));f.write(header)
            block=struct.pack('<f',.125)*262144
            for _ in range(96):f.write(block)
        cp=nc(homes[0],'register',str(large))['checkpoint']
        shared=nc(homes[0],'publish-checkpoint',cp,'--fixture',timeout=600)
        received=eventually(lambda:nc(homes[1],'fetch',shared['record'],timeout=600),90)
        assert received['artifact']==cp
        manifest=json.loads((homes[1]/'artifacts'/cp).read_text())
        actual=homes[1]/'artifacts'/manifest['artifact']
        assert actual.stat().st_size==large.stat().st_size>64*1024*1024
        evidence['checks']['large_dkg_artifact']={'bytes':actual.stat().st_size,'checkpoint':cp,'publication':shared,'transport':'native DKG paged artifact protocol','ui_servers_started':False}
        print('Large checkpoint transferred and hash-verified through DKG',flush=True)
        # Corrupt a native DKG blob, prove no full artifact is committed, then resume.
        rows=request(dkg_homes[0],apis[0],'/api/query',{'contextGraphId':cg,'graphSuffix':'_shared_memory','sparql':f'SELECT ?delivery WHERE {{ GRAPH ?g {{ <urn:sha256:{manifest["artifact"]}> <urn:neural-commons:delivery:v1> ?delivery }} }}'})['result']['bindings']
        literal=rows[0]['delivery'];root=json.loads(json.loads(literal) if literal.startswith('"') else literal)
        root_file=dkg_homes[0]/'files'/root['sha256'][:2]/root['sha256'][2:]
        parts=json.loads(root_file.read_text())['parts'];last=parts[-1]
        blob_file=dkg_homes[0]/'files'/last['sha256'][:2]/last['sha256'][2:]
        retry_home=run/'retry-reader';retry_home.mkdir(mode=0o700)
        (retry_home/'config.json').write_text((homes[1]/'config.json').read_text())
        with open(blob_file,'r+b') as f:
            original=f.read(1);f.seek(0);f.write(bytes([original[0]^1]));f.flush();os.fsync(f.fileno())
        try:
            bad=subprocess.run([str(ROOT/'target/debug/nc'),'--home',str(retry_home),'fetch',shared['record']],capture_output=True,text=True,timeout=300)
            assert bad.returncode and ('integrity mismatch' in bad.stderr or 'hash_mismatch' in bad.stderr),bad.stderr
            assert not (retry_home/'artifacts'/manifest['artifact']).exists()
            cached_before=len(list((retry_home/'artifacts').iterdir()));assert cached_before>0
        finally:
            with open(blob_file,'r+b') as f:f.write(original);f.flush();os.fsync(f.fileno())
        nc(retry_home,'fetch',shared['record'],timeout=600)
        assert (retry_home/'artifacts'/manifest['artifact']).stat().st_size==actual.stat().st_size
        evidence['checks']['corrupt_dkg_blob_and_resume']={'rejected':True,'cached_verified_parts_before_retry':cached_before,'retry':'passed'}
        # Restart both real DKG daemons; fresh client storage must recover bytes from DKG disk.
        assert all((h/'store.nq').is_file() for h in dkg_homes),'DKG store persistence was not activated'
        for p in dkg_processes:os.killpg(p.pid,signal.SIGTERM)
        for p in dkg_processes:p.wait(timeout=30)
        for i in range(2):
            p=launch(dkg_homes[i],log_for(run/f'dkg-restarted-{i}.log'));processes.append(p)
            restored=wait_ready(dkg_homes[i],apis[i],p);assert restored['agentAddress']==identities[i]['agentAddress']
        request(dkg_homes[1],apis[1],'/api/connect',{'multiaddr':f'/ip4/127.0.0.1/tcp/{peers[0]}/p2p/{identities[0]["peerId"]}'},admin=True)
        cold=run/'cold-reader';cold.mkdir(mode=0o700);(cold/'config.json').write_text((homes[1]/'config.json').read_text())
        eventually(lambda:nc(cold,'fetch',shared['record'],timeout=600),120)
        assert (cold/'artifacts'/manifest['artifact']).stat().st_size==actual.stat().st_size
        evidence['checks']['dkg_cold_restart']={'same_identities':True,'fresh_client_artifacts':True,'bytes_verified':actual.stat().st_size}
        print('Corrupt DKG blob rejected; resume and cold DKG restart passed',flush=True)
        # Kill an actual supervisor/worker pair, then exercise durable restart.
        recovery_spec=json.loads((homes[0]/'artifacts'/fixture['candidates']['repair']['spec']).read_text())
        dataset=json.loads((homes[0]/'artifacts'/recovery_spec['dataset']).read_text())
        dataset['samples']=(dataset['samples']*683)[:4096]
        dataset_file=run/'recovery-dataset.json';dataset_file.write_text(json.dumps(dataset,separators=(',',':')))
        recovery_spec['dataset']=nc(homes[0],'put',str(dataset_file))['artifact']
        spec_file=run/'recovery-spec.json';spec_file.write_text(json.dumps(recovery_spec,separators=(',',':')))
        recovery_id=nc(homes[0],'put',str(spec_file))['artifact']
        parent=subprocess.Popen([str(ROOT/'target/debug/nc'),'--home',str(homes[0]),'evaluate',recovery_id],stdout=log_for(run/'interrupted-worker.log'),stderr=subprocess.STDOUT,start_new_session=True);processes.append(parent)
        until=time.monotonic()+5;worker=None
        while time.monotonic()<until and parent.poll() is None:
            rows=subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True).splitlines()
            for row in rows:
                cells=row.strip().split(None,2)
                if len(cells)==3 and cells[1]==str(parent.pid) and 'evaluation-worker' in cells[2]:worker=int(cells[0]);break
            if worker:break
            time.sleep(.01)
        assert worker is not None,'evaluator process was not observed'
        parent.kill();parent.wait()
        try:os.kill(worker,signal.SIGKILL)
        except ProcessLookupError:pass
        failed=subprocess.run([str(ROOT/'target/debug/nc'),'--home',str(homes[0]),'evaluate',recovery_id],capture_output=True,text=True,timeout=10)
        assert failed.returncode!=0 and 'interrupted' in failed.stderr
        retried=nc(homes[0],'evaluate',recovery_id,'--retry')
        assert retried['evaluation']['status']=='passed' and retried['evaluation']['process_id']!=worker
        evidence['checks']['killed_worker_restart']={'spec':recovery_id,'interrupted_pid':worker,'retry_report':retried['report'],'retry_pid':retried['evaluation']['process_id']}
        # Simulate the persisted boundary after an uncertain publication response.
        record=evidence['checks']['repair']['proposal']['record']
        db=sqlite3.connect(homes[0]/'journal.sqlite');db.execute("UPDATE publications SET state='sending' WHERE id=?",(record,));db.commit();db.close()
        reconciled=eventually(lambda:nc(homes[0],'share',record),90)
        assert reconciled.get('reconciled') is True
        evidence['checks']['uncertain_publication_reconciled']=True
        # Missing artifacts are explicit failures, not an empty/pass result.
        for i in range(2):
            p=subprocess.Popen([str(ROOT/'target/debug/nc'),'--home',str(homes[i]),'serve','--port',str(artports[i])],stdout=log_for(run/f'http-{i}.log'),stderr=subprocess.STDOUT,start_new_session=True);processes.append(p)
            def ready(i=i):
                with urllib.request.urlopen(f'http://127.0.0.1:{artports[i]}/',timeout=2) as r:assert r.status==200
            eventually(ready,10)
        missing='0'*64
        req=urllib.request.Request(f'http://127.0.0.1:{artports[0]}/api/artifact-metadata/{missing}',headers={'Authorization':'Bearer '+(homes[0]/'artifact.token').read_text()})
        try:urllib.request.urlopen(req,timeout=2);raise AssertionError('missing artifact returned success')
        except urllib.error.HTTPError as e:assert e.code==404
        try:urllib.request.urlopen(f'http://127.0.0.1:{artports[0]}/api/state',timeout=2);raise AssertionError('unauthenticated state returned success')
        except urllib.error.HTTPError as e:assert e.code==401
        evidence['checks']['missing_artifact_and_auth_rejection']=True
        # Verify graph authorization with an unrelated agent token on A's real daemon.
        private_cg=cg_suffix+'-private-check'
        request(dkg_homes[0],apis[0],'/api/context-graph/create',{'id':private_cg,'name':'Access check','allowedAgents':[identities[0]['agentAddress']],'participantAgents':[identities[0]['agentAddress']],'accessPolicy':1,'publishPolicy':1,'register':True},admin=True)
        outsider=request(dkg_homes[0],apis[0],'/api/agent/register',{'name':'access-denial-check'},admin=True)
        outsider_token=run/'denied-agent.token';outsider_token.write_text(outsider['authToken']);os.chmod(outsider_token,0o600)
        del outsider
        denied=run/'denied';denied.mkdir()
        denied_cfg=json.loads((homes[0]/'config.json').read_text());denied_cfg['context_graph']=private_cg;denied_cfg['dkg_token_file']=str(outsider_token)
        (denied/'config.json').write_text(json.dumps(denied_cfg))
        result=subprocess.run([str(ROOT/'target/debug/nc'),'--home',str(denied),'fetch','0'*64],capture_output=True,text=True,timeout=30)
        assert result.returncode!=0 and '403' in result.stderr,('expected explicit denied graph access',result.stderr)
        evidence['checks']['denied_graph_access']=True
        evidence['status']='passed' 
    except BaseException as e:
        evidence['status']='failed';evidence['error']=str(e);raise
    finally:
        (run/'validation.json').write_text(json.dumps(evidence,indent=2))
        for p in processes:
            if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
        for p in processes:
            try:p.wait(timeout=15)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        for f in logs:f.close()
        print('Validation:',run/'validation.json',flush=True)

if __name__=='__main__':main()
