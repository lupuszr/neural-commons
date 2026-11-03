#!/usr/bin/env python3
"""Compare all three frozen checkpoints on the continuation's final set.

The child/parent pair comes from independently reproduced DKG output; the root
reference is an additional local measurement, never fed back into the search.
"""
import argparse
import json
import pathlib
import tempfile
from weight_agent import write, sha
from weight_handoff import artifact, load
from llm_runtime import load_model, materialize, score
from summarize_weight_result import summarize


def compare(run):
    validation_path=run/('recovered-validation.json' if (run/'recovered-validation.json').exists() else 'validation.json')
    validation=json.loads(validation_path.read_text())
    if validation['status']!='passed' or not validation['services_stopped']:
        raise ValueError('complete DKG chain validation first')
    directory=run/'continuation'
    handoff,_=load(directory,sha(directory/'model/model.safetensors'))
    root=directory/'parent-artifacts'
    original=json.loads(artifact(root,handoff['base_checkpoint']).read_text())
    output_id=validation['child_local']['evaluation']['evaluation']['outputs']
    child_artifacts=pathlib.Path(validation.get('child_artifact_directory',str(run/'b/artifacts')))
    output=json.loads(artifact(child_artifacts,output_id).read_text())
    if validation['child_remote']['evaluation']['outputs']!=output_id:
        raise ValueError('independent output mismatch')
    with tempfile.TemporaryDirectory(prefix='nc-chain-reference-') as tmp:
        materialize(tmp,{'':str(artifact(root,original['artifact']))},
                    {name:str(artifact(root,digest)) for name,digest in original['inference_artifacts'].items()})
        model,tokenizer=load_model(tmp)
        reference=score(model,tokenizer,json.loads((directory/'heldout.json').read_text()),
                        json.loads((directory/'config.json').read_text()))
    result={'schema':'nc/weight-chain-comparison/v1','dataset_sha256':sha(directory/'heldout.json'),
            'scope':'Same fixed new final set. M1/M2 output independently reproduced through DKG; M0 is an additional local reference measurement. No selection uses these results.',
            'root':reference,'inherited':output['details']['base'],'child':output['details']['candidate'],
            'guard':output['details']['guard'],'incremental':summarize(output),
            'child_output_sha256':output_id,'model_improvement_status':validation['model_improvement_status']}
    write(run/'chain-comparison.json',result)
    print(json.dumps({k:{n:v for n,v in result[k].items() if n!='predictions'} for k in ['root','inherited','child']},indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=pathlib.Path,required=True)
    compare(p.parse_args().run_dir.resolve())
