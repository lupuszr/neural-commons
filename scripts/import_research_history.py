#!/usr/bin/env python3
"""One-time, idempotent import of the existing 3D-print research evidence.

Historical facts stay in their source JSONs; no evaluation is rerun or synthesized.
New work must use Tracker.run / nc research run instead of this importer.
"""
import argparse
import hashlib
import json
from pathlib import Path
from research_tracker import ROOT, Tracker, measurements, split_role


NAMES = {
    'print-ai-pilot-2026-11-04': '3D print · initial camera audit (CLIP)',
    'print-ai-corpus-2026-11-04': '3D print · 283-photo camera audit (CLIP)',
    'print-synthetic-2026-11-05': '3D print · 24 synthetic images (CLIP)',
    'print-synthetic-200-2026-11-05': '3D print · 200 synthetic images (CLIP)',
    'print-real-web-2026-11-05': '3D print · real photos, task readout (CLIP)',
    'print-network-edit-2026-11-05': '3D print · internal vision edits (CLIP)',
    'print-agent-discovery-2026-11-05': '3D print · adaptive vision edits (CLIP)',
    'print-chain-discovery-2026-11-05': '3D print · vision A → B chain (CLIP)',
    'print-llm-discovery-2026-11-05': '3D print · LLM four-defect discovery',
    'print-llm-protected-2026-11-05': '3D print · LLM language preservation',
    'print-llm-photo-discovery-2026-11-05': '3D print · LLM web photos (A retained)',
    'print-llm-continuation-2026-11-05': '3D print · LLM camera continuation',
    'print-llm-robust-2026-11-05': '3D print · LLM visible failures · 240 photos',
}
ACTIVE = 'print-llm-robust-2026-11-05'


def read(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def time_of(path):
    data = read(path) if path.suffix == '.json' else {}
    if isinstance(data, dict):
        for key in ['created_at', 'finished_at', 'time']:
            if isinstance(data.get(key), (int, float)):
                return data[key]
    return path.stat().st_mtime


def import_experiment(home, directory):
    tracker = Tracker(home, directory.name)
    protocol = read(directory / 'protocol.json')
    source = read(directory / 'model-source.json')
    model = source.get('model_id') or protocol.get('model', 'openai/clip-vit-base-patch32')
    if isinstance(model, dict):
        model = model.get('model_id', 'Unspecified model')
    objective = protocol.get('objective') or protocol.get('scope') or 'Evaluate visible 3D-print defects using the recorded protocol.'
    scope = protocol.get('scope') or protocol.get('data_limitations') or protocol.get('data_limit') or 'Exploratory research; see the original protocol and evidence.'
    if not isinstance(scope, str):
        scope = json.dumps(scope)
    if 'llm' not in directory.name:
        scope = 'Archived non-LLM experiment. ' + scope
    evidence = [p for p in [directory/'protocol.json', directory/'manifest.json', directory/'model-source.json', directory/'agent-decisions.jsonl'] if p.is_file()]
    count = 0

    def emit(kind, data, round_id=None, files=(), key=None, at=None):
        nonlocal count
        identity = 'import-' + hashlib.sha256((directory.name + ':' + str(round_id) + ':' + kind + ':' + (key or '')).encode()).hexdigest()[:40]
        files = [p for p in files if p.is_file()]
        tracker.record(kind, data, round_id=round_id, evidence=files, event_id=identity,
                       historical=True, occurred_at=at or (time_of(files[0]) if files else time_of(directory/'protocol.json')))
        count += 1

    definition = dict(name=NAMES[directory.name], model=model, objective=objective, scope=scope,
                      controller='Current conversation assistant', dataset=protocol,
                      source_directory=str(directory), history_import='Reconstructed from saved artifacts; original times are evidence timestamps or file modification times.')
    if protocol.get('parent_sha256') or protocol.get('frozen_a_sha256'):
        definition['parent_sha256'] = protocol.get('parent_sha256') or protocol['frozen_a_sha256']
    emit('experiment', definition, files=evidence)
    tasks = []

    def queue(round_id, label, kind, hypothesis, result, files, operation=None, decision=None, at=None, participant=None):
        files = [p for p in files if p.is_file()]
        tasks.append(dict(round_id=round_id, label=label, kind=kind, hypothesis=hypothesis,
                          result=result, files=files, operation=operation, decision=decision,
                          at=at or (time_of(files[0]) if files else time_of(directory/'protocol.json')), participant=participant))

    actions = {read(p).get('name'): p for p in directory.glob('*action*.json') if isinstance(read(p), dict) and read(p).get('name')}
    feedbacks = {p.parent.name: p for p in directory.glob('*/feedback.json')}
    for name in sorted(set(actions) | set(feedbacks)):
        feedback_path = feedbacks.get(name)
        action_path = actions.get(name) or directory/name/'action.json'
        action = read(action_path)
        feedback = read(feedback_path) if feedback_path else {}
        files = [action_path] + ([feedback_path] if feedback_path else [])
        files += [p for p in (directory/name).glob('*.json') if p not in files]
        data = dict(status='completed' if feedback_path else 'interrupted',
                    summary='Historical numerical feedback; use the recorded split roles and final decision below.' if feedback_path else 'An action was saved, but no completed feedback artifact was found.',
                    measurements=measurements(feedback.get('metrics', {})))
        for key in ['changed_tensors', 'changed_values', 'replacement_sha256', 'parent_sha256']:
            if key in feedback:
                data[key] = feedback[key]
        if 'text_validation' in feedback:
            for key in ['perplexity_ratio_to_a','argmax_agreement_to_a']:
                if key in feedback['text_validation']:
                    data['measurements'].append(dict(label='Text validation / '+key,split='selection',value=feedback['text_validation'][key]))
        decision = None
        if directory.name == ACTIVE and name == 'b-gated-01':
            data['summary'] = 'Camera selection improves 21/40 → 26/40; retired web reference declines 56/68 → 53/68. Final test not run.'
            parents = {'camera / b_development':55, 'camera / b_selection':21, 'retired_reference / retired_web_reference':56}
            for m in data['measurements']:
                if m['label'] in parents:
                    m['parent_correct'] = parents[m['label']]
            decision = dict(verdict='not_selected',reason='Fails the precommitted web-retention requirement. Continue discovery from retained A; do not freeze this candidate for final testing.')
        queue(name,name.replace('-',' ').title(),'probe',action.get('hypothesis') or 'Original hypothesis is recorded in the attached action or decision ledger.',data,files,
              operation=action,decision=decision,at=time_of(action_path) if action_path.is_file() else time_of(feedback_path),
              participant='B' if name.startswith('b-') else 'A' if name.startswith('a-') else None)

    # Earlier bounded searches recorded one row per candidate, rather than a folder.
    for filename in ['search-trace.json','selection-trace.json']:
        path=directory/filename
        if not path.is_file(): continue
        trace=read(path); trials=trace if isinstance(trace,list) else trace.get('trials',[])
        for i,trial in enumerate(trials):
            name=trial.get('name',str(i)); ms=measurements(trial)
            for split in ['development','selection']:
                if split+'_accuracy' in trial:
                    ms.append(dict(label=split+' accuracy',split=split,value=trial[split+'_accuracy']))
            queue('search-'+str(i),name,'probe',protocol.get('rationale') or 'Candidate from the predeclared bounded search; see protocol and complete search trace.',
                  dict(status='completed',summary='Historical search candidate; selection is exploratory.',measurements=ms),[path],operation=trial,at=time_of(path)+i*.0001)

    for filename in ['inspection.json','b-inspection.json','data-audit.json','visibility-amendment.json']:
        path=directory/filename
        if path.is_file():
            data=read(path)
            queue(filename[:-5],filename[:-5].replace('-',' ').title(),'baseline' if 'inspection' in filename else 'data_audit',
                  'Inspect the inherited model or data before selecting an edit.',
                  dict(status='completed',summary=data.get('reason','Historical inspection; original measurements and scope are attached.'),measurements=measurements(data.get('metrics',{}))),[path])

    for stage in ['a','b']:
        folder=directory/(stage+'-frozen');path=folder/'commitment.json'
        if path.is_file() and not folder.is_symlink():
            data=read(path)
            queue(stage+'-freeze',stage.upper()+' candidate frozen','freeze',data.get('reason','Freeze the chosen candidate before final evaluation.'),
                  dict(status='completed',summary='Candidate identity committed; freezing is not acceptance.',measurements=[]),[path],operation=data,participant=stage.upper())

    for filename in ['handoff.json','context-amendment-handoff.json','return-handoff.json','dkg-evidence.json']:
        path=directory/filename
        if path.is_file():
            data=read(path)
            if data.get('complete') is not True and filename != 'dkg-evidence.json': continue
            queue(filename[:-5],filename[:-5].replace('-',' ').title(),'dkg_handoff',
                  'Share checkpoint and evidence between the two local DKG participants; verify received identity.',
                  dict(status='completed',summary='Transfer evidence recorded. Transfer/replay proves identity, not model improvement.',measurements=[]),[path])

    evaluation=read(directory/'evaluation.json'); decision=read(directory/'final-decision.json')
    if evaluation.get('reports') or evaluation.get('baseline'):
        ms=[];reports=evaluation.get('reports',{})
        parent=None
        for stage,report in reports.items():
            score=report if 'correct' in report else report.get('metrics',{})
            stage_ms=measurements(score,stage.upper()+' · final','final')
            if parent is not None and len(stage_ms)==1 and parent.get('n') == stage_ms[0].get('total'):
                stage_ms[0]['parent_correct']=parent['correct']
            ms+=stage_ms
            if 'correct' in score:parent=score
            if 'domains' in report:
                ms+=measurements(report['domains'],stage.upper()+' · final domains','final')
            if 'text_smoke_expected_matches' in report:
                ms.append(dict(label=stage.upper()+' · expected text answers',split='regression' if directory.name==ACTIVE else 'final',
                               correct=report['text_smoke_expected_matches'],total=len(report.get('text_smoke_controls',[]))))
        if not reports:
            for stage in ['baseline','candidate']:
                ms+=measurements(evaluation[stage].get('metrics',{}),stage+' · final','final')
        reason=decision.get('reason') or decision.get('decision') or 'Historical final evaluation; inspect the attached verdict.'
        verdict='not_promoted' if decision.get('promoted_for_showcase') is False else 'rejected' if decision.get('accepted') is False or 'reject' in reason.lower() else 'inconclusive'
        if directory.name=='print-llm-discovery-2026-11-05': verdict='rejected'
        queue('final-evaluation','Final evaluation · original → A → B','final_evaluation',
              'Compare frozen versions on the same committed inputs, then apply the acceptance criteria.',
              dict(status='completed',summary=reason,measurements=ms),[directory/'evaluation.json',directory/'final-decision.json'],
              decision=dict(verdict=verdict,reason=reason))

    # Legacy baselines/task-readout pilots keep their original result, including all
    # source labels and per-split metrics. Do not invent a generative-LLM verdict.
    path=directory/'result.json'
    if path.is_file():
        data=read(path);ms=[]
        for split,metric in data.get('splits',{}).items():
            if not metric.get('n'):continue
            for stage in ['base','candidate']:
                if stage+'_accuracy' in metric:
                    ms.append(dict(label=stage+' / '+split,split=split_role(split),value=metric[stage+'_accuracy']))
        queue('legacy-result','Recorded pilot result','baseline' if 'ai-' in directory.name else 'final_evaluation',
              'Evaluate the pilot under its original scope; this is not a generative-LLM improvement.',
              dict(status='completed',summary='Archived pilot result. Inspect source-label and synthetic-data limits in the protocol.',measurements=ms),[path,directory/'verification.json'])

    for task in sorted(tasks,key=lambda t:(t['at'],t['round_id'])):
        definition=dict(label=task['label'],kind=task['kind'],hypothesis=task['hypothesis'])
        if task['participant']:definition['participant']=task['participant']
        if task['operation']:definition['operation']=task['operation']
        if task['result'].get('parent_sha256'):definition['parent_sha256']=task['result']['parent_sha256']
        emit('round',definition,task['round_id'],at=task['at'])
        emit('result',task['result'],task['round_id'],files=task['files'],at=task['at'])
        if task['decision']:emit('decision',task['decision'],task['round_id'],at=task['at'])
    status='in_progress' if directory.name==ACTIVE else 'completed' if 'llm' in directory.name else 'archived'
    summary=decision.get('reason') or decision.get('decision') or 'Historical experiment imported with its original evidence and scope.'
    if directory.name==ACTIVE:
        summary='Research in progress. First probe improves camera selection but loses web accuracy; it is not selected. Final 120-photo evaluation has not run.'
    emit('status',dict(status=status,summary=summary),key='import-status')
    return dict(experiment=directory.name,rounds=len(tasks),events=count)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--home',required=True);parser.add_argument('--only')
    args=parser.parse_args()
    for name in NAMES:
        if args.only and args.only!=name:continue
        directory=ROOT/'artifacts'/name
        if directory.is_dir():print(json.dumps(import_experiment(args.home,directory)),flush=True)


if __name__=='__main__':main()
