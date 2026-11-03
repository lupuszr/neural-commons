#!/usr/bin/env python3
"""Build current canary in an isolated checkout, preserving the user's DKG tree."""
import argparse,json,os,pathlib,shutil,subprocess
import dkg_patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
def run(args,cwd):subprocess.run(args,cwd=cwd,check=True)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dkg-repo',type=pathlib.Path,default=pathlib.Path.home()/'projects/dkg-v9');args=parser.parse_args()
    repo=args.dkg_repo.resolve();runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True);source=runtime/'dkg-source'
    run(['git','fetch','origin','testnet-canary'],repo)
    sha=subprocess.check_output(['git','rev-parse','origin/testnet-canary'],cwd=repo,text=True).strip()
    if not source.exists():run(['git','worktree','add','--detach',str(source),sha],repo)
    else:
        dkg_patch.remove(source)
        changed=subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=source,text=True)
        if changed:raise RuntimeError('Isolated DKG source has tracked edits; preserve them before rerunning setup')
        run(['git','checkout','--detach',sha],source)
    dkg_patch.apply(source)
    run(['pnpm','install','--frozen-lockfile'],source)
    # Package scripts can accidentally use a different node on PATH. Invoke node-gyp
    # with the same node used for the actual daemon when the native ABI check fails.
    node=shutil.which('node');assert node
    test=[node,'-e','const D=require("./packages/cli/node_modules/better-sqlite3");new D(":memory:").close()']
    if subprocess.run(test,cwd=source,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        npm=pathlib.Path(shutil.which('npm')).resolve()
        gyp=npm.parent.parent/'node_modules/node-gyp/bin/node-gyp.js'
        if not gyp.is_file():raise RuntimeError('Matching Node native addon build requires npm bundled node-gyp')
        package=(source/'packages/cli/node_modules/better-sqlite3').resolve()
        run([node,str(gyp),'rebuild','--release'],package)
        run(test,source)
    run(['pnpm','run','build:runtime:packages'],source)
    hardhat=subprocess.check_output([node,'-p','require.resolve("hardhat/internal/cli/bootstrap")'],cwd=source/'packages/evm-module',text=True).strip()
    run([node,hardhat,'compile','--config','hardhat.devnet.config.ts'],source/'packages/evm-module')
    run(['cargo','build','--locked','--workspace'],ROOT)
    (runtime/'build.json').write_text(json.dumps({'dkg_source':sha,'patch_sha256':__import__('hashlib').sha256(dkg_patch.PATCH.read_bytes()).hexdigest(),'node':subprocess.check_output([node,'--version'],text=True).strip()},indent=2))
    print('Ready: cargo run --locked --bin nc -- demo')
if __name__=='__main__':main()
