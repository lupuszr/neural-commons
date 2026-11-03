#!/usr/bin/env python3
"""Finish a preserved interrupted chain using a new local DKG reproduction pair.

The original parent receipt and controller transcript stay immutable. The new
transport phase has distinct identities, recorded explicitly rather than being
presented as uninterrupted work by the first pair.
"""
import argparse
import json
import pathlib
import subprocess
import sys
from weight_agent import ROOT, sha, write
from weight_handoff import load


def finish(run, reproduction, failed_reproductions=()):
    original_path=run/'validation.json'
    original=json.loads(original_path.read_text())
    if original['status']!='failed' or not original['services_stopped'] or 'parent_remote' not in original:
        raise ValueError('requires a stopped interrupted chain with a verified parent receipt')
    if original['parent_remote']['evaluation']['status']!='passed':
        raise ValueError('inherited model did not pass reproduction')
    directory=run/'continuation';selected=run/'search/selected'
    handoff,_=load(directory,sha(directory/'model/model.safetensors'))
    session=json.loads((selected/'session.json').read_text())
    if (sha(directory/'handoff.json')!=original['handoff_sha256'] or
        session['commitment']['handoff_sha256']!=original['handoff_sha256'] or
        handoff['candidate_checkpoint']!=original['parent_local']['candidate']):
        raise ValueError('resume changed inherited lineage')
    if (run/'recovered-validation.json').exists():
        raise ValueError('recovery already finalized')
    failed = []
    for path in failed_reproductions:
        attempt = json.loads((path/'validation.json').read_text())
        if attempt['status']!='failed' or not attempt['services_stopped']:
            raise ValueError('prior reproduction attempt must be stopped and failed')
        failed.append({'directory':str(path),'validation_sha256':sha(path/'validation.json'),
                       'identities':attempt.get('identities',[])})
    subprocess.run([sys.executable,str(ROOT/'scripts/weight_dkg_validation.py'),
                    '--directory',str(directory),'--session',str(selected),
                    '--run-dir',str(reproduction)],check=True)
    child=json.loads((reproduction/'validation.json').read_text())
    if child['status']!='passed' or not child['services_stopped']:
        raise ValueError('child transport reproduction did not finish')
    if child['a']['base']!=original['parent_local']['candidate']:
        raise ValueError('child base is not the inherited checkpoint ID')
    combined={'schema':'nc/recovered-weight-chain-validation/v1','status':'passed',
              'scope':'Two completed sequential local DKG transport phases on one machine. The controller resumed after a CLI interruption; the final child used a new pair. Additional failed transport attempts and their identities are retained separately.',
              'services_stopped':True,'model_improvement_status':child['a']['evaluation']['evaluation']['status'],
              'original_phase_sha256':sha(original_path),'reproduction_phase_sha256':sha(reproduction/'validation.json'),
              'child_artifact_directory':str(reproduction/'a/artifacts'),
              'reproduction_directory':str(reproduction),
              'parent_identities':original['identities'],'child_identities':child['identities'],
              'failed_reproduction_attempts':failed,
              'parent_local':original['parent_local'],'parent_remote':original['parent_remote'],
              'parent_proposal':original['parent_proposal'],
              'child_local':child['a'],'child_remote':child['b'],'child_proposal':child['proposal'],
              'child_readback':child['a_readback'],'review_readback':child['review_readback'],
              'handoff_sha256':original['handoff_sha256'], 'exact_parent_checkpoint_link':True,
              'b_started_without_artifacts':original['b_started_without_artifacts'],
              'provenance_transferred':child['provenance_transferred']}
    write(run/'recovered-validation.json',combined)
    print('Recovered chain verified; model improvement:',combined['model_improvement_status'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=pathlib.Path,required=True)
    p.add_argument('--reproduction-dir',type=pathlib.Path,required=True)
    p.add_argument('--failed-reproduction',type=pathlib.Path,action='append',default=[])
    a=p.parse_args();finish(a.run_dir.resolve(),a.reproduction_dir.resolve(),[p.resolve() for p in a.failed_reproduction])
