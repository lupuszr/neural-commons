#!/usr/bin/env python3
"""Export a completed chain's audit evidence without redistributing news text."""
import argparse
import hashlib
import json
import pathlib
import shutil
from weight_agent import sha
from weight_handoff import artifact


def redact(value):
    if isinstance(value,list):return [redact(v) for v in value]
    if isinstance(value,dict):
        return {('text_sha256' if k=='text' and isinstance(v,str) else k):
                (hashlib.sha256(v.encode()).hexdigest() if k=='text' and isinstance(v,str) else redact(v))
                for k,v in value.items()}
    return value


def export(run,out):
    validation_path=run/('recovered-validation.json' if (run/'recovered-validation.json').exists() else 'validation.json')
    validation=json.loads(validation_path.read_text())
    if validation['status']!='passed' or not validation['services_stopped']:
        raise ValueError('complete chain validation first')
    out.mkdir(parents=True,exist_ok=False)
    manifest={'note':'News text is replaced with SHA256 in public controller/data copies. Original full artifacts were exchanged through DKG. This manifest distinguishes original and public file hashes.','files':{}}
    def copy(path,name,redacted=False):
        destination=out/name;destination.parent.mkdir(parents=True,exist_ok=True)
        if redacted:
            if path.suffix=='.jsonl':data=''.join(json.dumps(redact(json.loads(l)),allow_nan=False)+'\n' for l in path.read_text().splitlines())
            else:data=json.dumps(redact(json.loads(path.read_text())),indent=2,allow_nan=False)+'\n'
            destination.write_text(data)
        else:shutil.copyfile(path,destination)
        manifest['files'][name]={'original_sha256':sha(path),'public_sha256':sha(destination),'source_text_redacted':redacted}
    copy(validation_path,'dkg-chain-validation.json')
    if validation_path.name=='recovered-validation.json':
        copy(run/'validation.json','interrupted-phase.json')
        copy(pathlib.Path(validation['reproduction_directory'])/'validation.json','reproduction-phase.json')
        for index,attempt in enumerate(validation.get('failed_reproduction_attempts', [])):
            copy(pathlib.Path(attempt['directory'])/'validation.json',f'failed-reproduction-{index+1}.json')
    copy(run/'chain-comparison.json','chain-comparison.json')
    if (run/'posthoc-prior-task.json').exists():
        copy(run/'posthoc-prior-task.json','posthoc-prior-task.json')
    directory=run/'continuation';session=run/'search/selected'
    for name in ['handoff.json','parent-diff.json','source.json','config.json','policy.json','guard.json','guard-config.json']:
        copy(directory/name,name)
    for name in ['development','selection','heldout']:
        copy(directory/(name+'.json'),name+'.public.json',True)
    for name in ['session.json','selection-report.json','transcript.jsonl']:
        copy(session/name,name.replace('.json','.public.json'),True)
    for name in ['commitment.json','spec.json','result.json']:
        copy(session/name,name)
    home=pathlib.Path(validation.get('child_artifact_directory',str(run/'b/artifacts')))
    copy(artifact(home,validation['child_local']['evaluation']['evaluation']['outputs']),'heldout-output.json')
    copy(home.parent/'llm-runtime.json','runtime.json')
    for label,result in [('parent',validation['parent_local']),('child',validation['child_local'])]:
        for key in ['base','candidate','patch','spec']:
            copy(artifact(home,result[key]),label+'-'+key+'.json')
    for label,key in [('parent-proposal','parent_proposal'),('child-proposal','child_proposal')]:
        copy(artifact(home,validation[key]['record']),label+'.json')
    for source in ['tested-source','resume-source']:
        for path in (run/source).rglob('*'):
            if path.is_file():copy(path,str(path.relative_to(run)))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Exported chain evidence:',out)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True)
    a=p.parse_args();export(a.run_dir.resolve(),a.output.resolve())
