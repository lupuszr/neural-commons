"""Disposable local EVM only. The endpoint is allocated by the demo, never user supplied."""
import json,os,pathlib,subprocess,time,urllib.request
from dkg_runtime import SOURCE,ROOT
EVM=SOURCE/'packages/evm-module'
def rpc(url,method,params):
    req=urllib.request.Request(url,json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),{'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r:body=json.load(r)
    if 'error' in body:raise RuntimeError(str(body['error']))
    return body['result']
def cli():
    return subprocess.check_output(['node','-p','require.resolve("hardhat/internal/cli/bootstrap")'],cwd=EVM,text=True).strip()
def start(run,port,processes,log_for):
    url=f'http://127.0.0.1:{port}'
    p=subprocess.Popen(['node',cli(),'node','--hostname','127.0.0.1','--port',str(port),'--no-deploy','--config','hardhat.devnet.config.ts'],cwd=EVM,stdout=log_for(run/'chain.log'),stderr=subprocess.STDOUT,start_new_session=True);processes.append(p)
    until=time.monotonic()+30
    while True:
        try:
            assert rpc(url,'eth_chainId',[])=='0x7a69';break
        except OSError:
            if p.poll() is not None or time.monotonic()>until:raise RuntimeError('local chain failed to start')
            time.sleep(.25)
    contracts_file=EVM/'deployments/localhost_contracts.json'
    original=contracts_file.read_bytes() if contracts_file.exists() else None
    try:
        with open(run/'chain-deploy.log','w') as out:
            subprocess.run(['node',cli(),'deploy','--network','localhost','--config','hardhat.devnet.config.ts','--reset','--no-compile'],cwd=EVM,env={**os.environ,'RPC_LOCALHOST':url},stdout=out,stderr=subprocess.STDOUT,check=True,timeout=180)
        deployed=contracts_file.read_bytes()
        (run/'local-contracts.json').write_bytes(deployed)
        contracts=json.loads(deployed)['contracts']
    finally:
        if original is None:contracts_file.unlink(missing_ok=True)
        else:contracts_file.write_bytes(original)
    # Mine fresh blocks so the ordinary finalized authority reader can establish absence.
    rpc(url,'hardhat_mine',['0x40'])
    rpc(url,'evm_setIntervalMining',[1000])
    return {'type':'evm','rpcUrl':url,'rpcUrls':[url],'walletRpcUrls':[url],'hubAddress':contracts['Hub']['evmAddress'],'chainId':'hardhat:31337','confirmations':1},contracts['Token']['evmAddress']
def fund(home,chain,token):
    env={**os.environ,'NC_DEMO_DKG_HOME':str(home),'NC_DEMO_RPC':chain['rpcUrl'],'NC_DEMO_TOKEN':token}
    # Keys stay within DKG's encrypted wallet store. Only throwaway local balances change.
    code='''import {loadOpWallets} from '@origintrail-official/dkg-agent';
import {ethers} from 'ethers';
const w=await loadOpWallets(process.env.NC_DEMO_DKG_HOME);
const p=new ethers.JsonRpcProvider(process.env.NC_DEMO_RPC);
if ((await p.getNetwork()).chainId!==31337n) throw Error('refusing nonlocal chain');
const t=new ethers.Contract(process.env.NC_DEMO_TOKEN,['function mint(address,uint256)'],await p.getSigner(0));
for (const v of [w.adminWallet,...w.wallets]) {
 if (!v) continue;
 await p.send('hardhat_setBalance',[v.address,ethers.toBeHex(ethers.parseEther('100'))]);
 await (await t.mint(v.address,ethers.parseEther('1000000'))).wait();
}
p.destroy();'''
    subprocess.run(['node','--input-type=module','-e',code],cwd=SOURCE/'packages/cli',env=env,check=True,timeout=45,stdout=subprocess.DEVNULL)
