#!/usr/bin/env python3
"""Configure isolated local DKG daemons with private participant credentials."""
import json, os, pathlib, secrets, subprocess, time, urllib.request, urllib.error, hashlib, signal

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.runtime/dkg-source'

def request(home, port, path, body=None, admin=False):
    token=(home/('auth.token' if admin or not (home/'agent.token').exists() else 'agent.token')).read_text().strip()
    req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: return json.load(r)
    except urllib.error.HTTPError as e: raise RuntimeError(f'{path}: HTTP {e.code}: {e.read(4096).decode()}') from None

def config(home, port, peerport, number, chain):
    home.mkdir(parents=True,exist_ok=True)
    os.chmod(home,0o700)
    if not (home/'auth.token').exists():
        (home/'auth.token').write_text(secrets.token_hex(32));os.chmod(home/'auth.token',0o600)
    cfg={'name':f'neural-commons-{number}','networkConfig':'neural-commons-local','apiHost':'127.0.0.1','apiPort':port,'listenPort':peerport,'nodeRole':'edge','relay':'none','lanAddressesEnabled':True,'bootstrapPeers':[],'contextGraphs':[],'chain':chain,'store':{'backend':'oxigraph-worker','options':{'path':str(home/'store.nq')}},'auth':{'enabled':True},'autoUpdate':{'enabled':False},'telemetry':{'enabled':False,'logs':{'enabled':False}},'publisher':{'enabled':False}}
    (home/'config.json').write_text(json.dumps(cfg,indent=2))

def setup_network():
    overlay={'networkName':'Neural Commons isolated local demo','genesisId':'base-testnet','networkId':json.loads((SOURCE/'network/testnet.json').read_text())['networkId'],'genesisVersion':1,'relays':[],'defaultContextGraphs':[],'defaultNodeRole':'edge','autoUpdate':{'enabled':False}}
    (SOURCE/'network/neural-commons-local.json').write_text(json.dumps(overlay))

def launch(home,log):
    return subprocess.Popen(['node',str(SOURCE/'packages/cli/dist/cli.js'),'start','--foreground'],env={**os.environ,'DKG_HOME':str(home)},cwd=SOURCE,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)

def wait_ready(home,port,process):
    deadline=time.monotonic()+90;last=None
    while time.monotonic()<deadline:
        if process.poll() is not None: raise RuntimeError(f'DKG exited: {process.returncode}; inspect {home}/daemon-output.log')
        try:
            request(home,port,'/api/agent/identity')
            if not (home/'agent.token').exists():
                registered=request(home,port,'/api/agent/register',{'name':'neural-commons-participant','framework':'Neural Commons'},admin=True)
                (home/'agent.token').write_text(registered['authToken']);os.chmod(home/'agent.token',0o600)
                del registered
            return request(home,port,'/api/agent/identity')
        except (OSError,RuntimeError) as e:last=e;time.sleep(.5)
    raise RuntimeError(f'DKG startup deadline exceeded: {last}')
