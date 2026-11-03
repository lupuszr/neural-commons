#!/usr/bin/env python3
"""One supplementary old-task check after freezing the continuation candidate."""
import argparse
import json
import pathlib
import tempfile
from weight_agent import sha, write
from weight_handoff import load, artifact
from llm_runtime import materialize, load_model, score


def check(run, previous):
    validation_path=run/('recovered-validation.json' if (run/'recovered-validation.json').exists() else 'validation.json')
    validation=json.loads(validation_path.read_text())
    if validation['status']!='passed' or not validation['services_stopped']:
        raise ValueError('complete final DKG evaluation first')
    directory=run/'continuation';session=json.loads((run/'search/selected/session.json').read_text())
    handoff,_=load(directory,session['commitment']['target_sha256']);root=directory/'parent-artifacts'
    parent_spec=json.loads(artifact(root,handoff['spec']).read_text())
    if sha(previous/'heldout.json')!=parent_spec['dataset'] or sha(previous/'config.json')!=parent_spec['config']:
        raise ValueError('old task does not match the inherited experiment')
    parent_output=json.loads(artifact(root,handoff['evaluation_output']).read_text())
    candidate=run/'search/selected/candidate.safetensors'
    if sha(candidate)!=session['candidate_sha256']:raise ValueError('frozen child changed')
    with tempfile.TemporaryDirectory(prefix='nc-prior-task-') as tmp:
        materialize(tmp,{'':str(candidate)},
                    {name:str(artifact(root,digest)) for name,digest in handoff['inference_artifacts'].items()})
        model,tokenizer=load_model(tmp)
        result=score(model,tokenizer,json.loads((previous/'heldout.json').read_text()),json.loads((previous/'config.json').read_text()))
    before=parent_output['details']['candidate']
    evidence={'schema':'nc/prior-task-diagnostic/v1',
              'scope':'Previously exposed first-round final news set; supplementary local regression check after the second final evaluation, never used for selection.',
              'dataset_sha256':parent_spec['dataset'],'parent_output_sha256':handoff['evaluation_output'],
              'child_sha256':session['candidate_sha256'],'inherited':before,'child':result,
              'accuracy_difference':result['accuracy']-before['accuracy'],
              'nll_reduction':before['label_nll']-result['label_nll']}
    write(run/'posthoc-prior-task.json',evidence)
    print(json.dumps({k:{n:v for n,v in evidence[k].items() if n!='predictions'} for k in ['inherited','child']},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=pathlib.Path,required=True)
    p.add_argument('--previous',type=pathlib.Path,required=True);a=p.parse_args();check(a.run_dir.resolve(),a.previous.resolve())
