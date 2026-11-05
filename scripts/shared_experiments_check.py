#!/usr/bin/env python3
"""Real two-node DKG invite -> discover -> UI download -> reproduce -> readback.

Uses a small labelled fixture and disposable local EVM; no controller/model API
calls and no public-chain writes. Always stops the services it started.
"""
import argparse, json, os, pathlib, secrets, signal, subprocess, time, urllib.request, urllib.parse, urllib.error
import local_chain
from demo import port
from dkg_runtime import ROOT, SOURCE, config, setup_network, launch, wait_ready, request


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--public',action='store_true');options=parser.parse_args()
    run=ROOT/'.runtime'/('shared-flow-'+time.strftime('%Y%m%d-%H%M%S'))
    run.mkdir(mode=0o700)
    processes=[];logs=[]
    evidence={'status':'running','scope':'two local DKG nodes; controlled model fixture; no paid controller or public-chain publication','access_policy':'public' if options.public else 'private','checks':{}}
    def log_for(p):
        f=p.open('w');logs.append(f);return f
    def nc(home,*args):
        result=subprocess.run([str(ROOT/'target/debug/nc'),'--home',str(home),*args],capture_output=True,text=True,timeout=180)
        if result.returncode:
            (run/'nc-error.log').write_text(result.stderr)
            raise RuntimeError('nc '+args[0]+' failed; inspect nc-error.log')
        return json.loads(result.stdout)
    def api(url):
        with urllib.request.urlopen(url,timeout=95) as r:return json.load(r)
    def eventually(fn,seconds=90):
        deadline=time.monotonic()+seconds;last=None
        while time.monotonic()<deadline:
            try:return fn()
            except (OSError,RuntimeError,AssertionError,subprocess.CalledProcessError) as error:last=error;time.sleep(.5)
        raise RuntimeError(f'DKG readiness/readback deadline exceeded: {last}')
    try:
        subprocess.run(['git','fetch','origin','testnet-canary'],cwd=SOURCE,check=True,capture_output=True)
        latest=subprocess.check_output(['git','rev-parse','origin/testnet-canary'],cwd=SOURCE,text=True).strip()
        built=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()
        if latest!=built:raise RuntimeError('Run scripts/setup.py: latest canary changed before validation')
        evidence['dkg_source']=built;setup_network()
        chain,chain_token=local_chain.start(run,port(),processes,log_for)
        homes=[run/'a',run/'b'];dh=[run/'dkg-a',run/'dkg-b'];apis=[port(),port()];peers=[port(),port()];web=[port(),port()];identities=[]
        for i in range(2):
            config(dh[i],apis[i],peers[i],i+301,chain);local_chain.fund(dh[i],chain,chain_token)
            process=launch(dh[i],log_for(run/f'dkg-{i}.log'));processes.append(process)
            identities.append(wait_ready(dh[i],apis[i],process));homes[i].mkdir(mode=0o700)
        evidence['identities']=identities
        cg=identities[0]['agentAddress'].lower()+'/nc-shared-'+secrets.token_hex(6)
        evidence['context_graph']=cg
        evidence['transport_setup']='Public subscription' if options.public else 'Both known host peers are allowed; only A is initially an authorized agent. B must pass the signed join/approval flow.'
        request(dh[1],apis[1],'/api/connect',{'multiaddr':f'/ip4/127.0.0.1/tcp/{peers[0]}/p2p/{identities[0]["peerId"]}'},admin=True)
        request(dh[0],apis[0],'/api/context-graph/create',{'id':cg,'name':'Neural Commons shared UI check','accessPolicy':0 if options.public else 1,'publishPolicy':1,**({} if options.public else {'allowedAgents':[identities[0]['agentAddress']],'participantAgents':[identities[0]['agentAddress']],'allowedPeers':[i['peerId'] for i in identities]}),'register':True})
        for i in range(2):
            (homes[i]/'ui.token').write_text(secrets.token_hex(32));os.chmod(homes[i]/'ui.token',0o600)
            cfg={'dkg_url':f'http://127.0.0.1:{apis[i]}','dkg_token_file':str(dh[i]/'agent.token'),'context_graph':cg,'artifact_origin':'dkg','artifact_token_file':str(homes[i]/'ui.token'),'require_token':False,'trusted_artifact_origin':None,'trusted_artifact_token_file':None}
            (homes[i]/'config.json').write_text(json.dumps(cfg))
            # Initialize the empty local journal without importing any artifacts.
            # B intentionally has no graph access yet, so nc init's access gate
            # must not be bypassed as evidence of membership.
            assert nc(homes[i],'identity')['agentAddress']==identities[i]['agentAddress']
            p=subprocess.Popen([str(ROOT/'target/debug/nc'),'--home',str(homes[i]),'serve','--port',str(web[i])],stdout=log_for(run/f'ui-{i}.log'),stderr=subprocess.STDOUT,start_new_session=True);processes.append(p)
            eventually(lambda:api(f'http://127.0.0.1:{web[i]}/api/state'),10)
        base=f'http://127.0.0.1:{web[1]}'
        if not options.public:
            try:api(base+'/api/shared-experiments');raise AssertionError('Unjoined participant could discover private graph')
            except urllib.error.HTTPError as e:assert e.code==503
            evidence['checks']['denied_before_join']=True
        invite=api(f'http://127.0.0.1:{web[0]}/api/context-graph/share')
        assert invite.get('invite_code')==cg+'\n'+identities[0]['peerId'],invite
        encoded=urllib.parse.quote(cg,safe='')
        if not options.public:
            signed=request(dh[1],apis[1],f'/api/context-graph/{encoded}/sign-join',{})
            joined=request(dh[1],apis[1],f'/api/context-graph/{encoded}/request-join',{'delegation':signed['delegation'],'agentName':'Shared UI collaborator','curatorPeerId':identities[0]['peerId']})
            if joined.get('status') not in ['approved','already-member'] and not joined.get('alreadyMember'):
                request(dh[0],apis[0],f'/api/context-graph/{encoded}/approve-join',{'agentAddress':identities[1]['agentAddress']})
        eventually(lambda:request(dh[1],apis[1],'/api/context-graph/subscribe',{'contextGraphId':cg}))
        eventually(lambda:api(base+'/api/shared-experiments'))
        evidence['checks']['native_invite_and_subscription']=True
        evidence['checks']['signed_join_approval']=not options.public
        fixture=nc(homes[0],'fixture');spec=fixture['candidates']['repair']['spec']
        original=nc(homes[0],'evaluate',spec)
        proposal=nc(homes[0],'propose',spec,'--fixture')
        def discovered():
            rows=api(base+'/api/shared-experiments')['records']
            row=next((r for r in rows if r['id']==proposal['record']),None)
            assert row is not None and not row['downloaded'];return row
        evidence['checks']['discovered_from_empty_participant']=eventually(discovered)
        result=subprocess.run(['node','scripts/shared_live_ui_check.cjs',base,proposal['record'],str(run)],cwd=ROOT,text=True,capture_output=True,timeout=480)
        (run/'browser.log').write_text(result.stdout+'\n'+result.stderr)
        if result.returncode:raise RuntimeError('Real browser flow failed; inspect browser.log')
        evidence['checks']['browser']=json.loads(result.stdout)
        state=api(base+'/api/state');report_id=next(j['report'] for j in state['jobs'] if j['spec']==spec)
        report=api(base+'/api/artifact-metadata/'+report_id)
        assert report['status']=='passed'
        assert report['candidate_mse']==original['evaluation']['candidate_mse']
        assert report['process_id']!=original['evaluation']['process_id']
        evaluations=[r for r in state['records'] if json.loads(r['record'])['kind']=='Evaluation']
        publication=next(r for r in evaluations if json.loads(r['record'])['artifact']==report_id)
        readback=eventually(lambda:nc(homes[0],'fetch',publication['id']))
        assert readback['author']==identities[1]['agentAddress'] and readback['relates_to']==proposal['record']
        evidence['checks']['independent_evaluation_and_author_readback']={'report':report_id,'publication':publication['id'],'status':report['status']}
        evidence['status']='passed'
        print('PASS: native invite/subscription, real DKG discovery, UI download/reproduce/share, owner readback. Graph policy: '+evidence['access_policy'],flush=True)
    except BaseException as e:
        evidence['status']='failed';evidence['error']=str(e)
        if 'base' in locals():
            try:
                state=api(base+'/api/state')
                evidence['partial_local_jobs']=state['jobs']
                evidence['partial_publication_states']=[p['state'] for p in state['publications']]
            except Exception:pass
        raise
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
