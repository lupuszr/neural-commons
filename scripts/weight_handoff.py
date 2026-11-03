"""Verified parent artifacts and exact numerical diffs for a second controller."""
import json
import pathlib

import torch
from safetensors.torch import load_file
from weight_agent import sha, write


def artifact(root, digest):
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('invalid artifact ID')
    path = root / digest
    if sha(path) != digest:
        raise ValueError('artifact hash mismatch')
    return path


def numerical_diff(before, after):
    old, new = load_file(before), load_file(after)
    if set(old) != set(new):
        raise ValueError('parent tensor inventory changed')
    rows = []
    for name, tensor in old.items():
        other = new[name]
        if tensor.dtype != other.dtype or tensor.shape != other.shape:
            raise ValueError('parent tensor layout changed')
        a, b = tensor.flatten(), other.flatten()
        indices, previous, current = [], [], []
        for start in range(0, a.numel(), 524288):
            x, y = a[start:start + 524288], b[start:start + 524288]
            positions = torch.nonzero(x != y).flatten()
            if positions.numel():
                indices.extend((positions + start).tolist())
                previous.extend(x[positions].float().tolist())
                current.extend(y[positions].float().tolist())
        if indices:
            rows.append({'tensor': name, 'dtype': str(tensor.dtype), 'shape': list(tensor.shape),
                         'indices': indices, 'before': previous, 'after': current,
                         'delta': [b - a for a, b in zip(previous, current)]})
    return {'schema': 'nc/numerical-weight-diff/v1', 'before_sha256': sha(before),
            'after_sha256': sha(after), 'changed_parameters': sum(len(r['indices']) for r in rows),
            'tensors': rows}


def inspect_diff(diff, tensor, start, count):
    if type(start) is not int or type(count) is not int or start < 0 or not 1 <= count <= 256:
        raise ValueError('invalid diff inspection range')
    row = next((r for r in diff['tensors'] if r['tensor'] == tensor), None)
    if row is None:
        raise ValueError('tensor has no recorded parent changes')
    return {'tensor': tensor, 'start': start, 'count': count,
            'changes': [{'index': i, 'before': a, 'after': b, 'delta': d}
                        for i, a, b, d in zip(row['indices'], row['before'], row['after'], row['delta'])
                        if start <= i < start + count]}


def prepare(home, proposal, evaluation, directory):
    """Consume already authenticated DKG receipt; all bytes must match their IDs."""
    from weight_experiment import nc
    record = nc(home, 'fetch', proposal)
    root = home / 'artifacts'
    stored_record = json.loads(artifact(root, proposal).read_text())
    if record != stored_record or record['kind'] != 'PatchProposal':
        raise ValueError('parent must be an authenticated proposal')
    spec = json.loads(artifact(root, record['artifact']).read_text())
    report = json.loads(artifact(root, evaluation).read_text())
    if report['spec'] != record['artifact'] or report['status'] != 'passed':
        raise ValueError('parent evaluation must pass this exact proposal')
    patch = json.loads(artifact(root, spec['patch']).read_text())
    if patch['parent'] != spec['base'] or patch['author'] != record['author']:
        raise ValueError('parent patch lineage/author mismatch')
    original = json.loads(artifact(root, spec['base']).read_text())
    inherited = json.loads(artifact(root, spec['candidate']).read_text())
    if original.get('shards') or inherited.get('shards'):
        raise ValueError('this Transformers continuation adapter requires a single-file checkpoint')
    session = json.loads(artifact(root, spec['evidence'][0]).read_text())
    if session['schema'] != 'nc/weight-agent-session/v1' or session['candidate_sha256'] != inherited['artifact'] or session['commitment']['target_sha256'] != original['artifact']:
        raise ValueError('parent session does not describe these checkpoints')
    # The Rust patch engine must independently reconstruct the inherited checkpoint.
    if nc(home, 'patch', 'apply', spec['base'], spec['patch'])['checkpoint'] != spec['candidate']:
        raise ValueError('parent patch reconstruction mismatch')
    output = json.loads(artifact(root, report['outputs']).read_text())
    if output['spec'] != record['artifact']:
        raise ValueError('parent evaluator output mismatch')
    directory.mkdir(parents=True, exist_ok=False)
    model = directory / 'model'
    model.mkdir()
    (model / 'model.safetensors').symlink_to(artifact(root, inherited['artifact']).resolve())
    for name, filename in {'model_config':'config.json', 'tokenizer':'tokenizer.json',
                           'tokenizer_config':'tokenizer_config.json', 'special_tokens':'special_tokens_map.json'}.items():
        (model / filename).symlink_to(artifact(root, inherited['inference_artifacts'][name]).resolve())
    diff = numerical_diff(artifact(root, original['artifact']), artifact(root, inherited['artifact']))
    if diff['changed_parameters'] != session['changed_parameters']:
        raise ValueError('parent changed-value count mismatch')
    write(directory / 'parent-diff.json', diff)
    metric = lambda row: {k:v for k,v in row.items() if k != 'predictions'}
    evidence_ids = sorted(set(record['artifacts'] + [proposal, evaluation, report['outputs']]))
    bundle = directory / 'parent-artifacts'
    bundle.mkdir()
    for digest in evidence_ids:
        (bundle / digest).symlink_to(artifact(root, digest).resolve())
    handoff = {'schema':'nc/weight-handoff/v1', 'proposal':proposal, 'spec':record['artifact'],
               'evaluation':evaluation, 'evaluation_output':report['outputs'], 'author':record['author'],
               'base_checkpoint':spec['base'], 'candidate_checkpoint':spec['candidate'], 'patch':spec['patch'],
               'original_sha256':original['artifact'], 'inherited_sha256':inherited['artifact'],
               'inference_artifacts':inherited['inference_artifacts'], 'evidence_ids':evidence_ids,
               'diff_sha256':sha(directory / 'parent-diff.json'),
               'controller':session['commitment']['controller'], 'backend':session['commitment']['backend'],
               'hypothesis':session['selected']['hypothesis'], 'operations':session['selected']['operations'],
               'development':metric(session['selected']['development']),
               'selection':metric(session['selected'].get('selection', {})),
               'previous_final':{k:metric(output['details'][k]) for k in ['base','candidate']},
               'changed_parameters':diff['changed_parameters'],
               'diff_summary':[{'tensor':r['tensor'],'dtype':r['dtype'],'shape':r['shape'],
                                'changed':len(r['indices']),'first_index':r['indices'][0],
                                'last_index':r['indices'][-1]} for r in diff['tensors']]}
    write(directory / 'handoff.json', handoff)
    return handoff


def load(directory, model_hash=None):
    handoff = json.loads((directory / 'handoff.json').read_text())
    if handoff['schema'] != 'nc/weight-handoff/v1':
        raise ValueError('invalid handoff schema')
    if model_hash is not None and handoff['inherited_sha256'] != model_hash:
        raise ValueError('continuation does not start from inherited checkpoint')
    if sha(directory / 'parent-diff.json') != handoff['diff_sha256']:
        raise ValueError('parent diff hash mismatch')
    root = directory / 'parent-artifacts'
    for digest in handoff['evidence_ids']:
        artifact(root, digest)
    record = json.loads(artifact(root, handoff['proposal']).read_text())
    spec = json.loads(artifact(root, handoff['spec']).read_text())
    parent = json.loads(artifact(root, handoff['candidate_checkpoint']).read_text())
    original = json.loads(artifact(root, handoff['base_checkpoint']).read_text())
    report = json.loads(artifact(root, handoff['evaluation']).read_text())
    patch = json.loads(artifact(root, handoff['patch']).read_text())
    diff = json.loads((directory / 'parent-diff.json').read_text())
    if (record['artifact'] != handoff['spec'] or record['author'] != handoff['author'] or
        spec['base'] != handoff['base_checkpoint'] or spec['candidate'] != handoff['candidate_checkpoint'] or
        spec['patch'] != handoff['patch'] or parent['artifact'] != handoff['inherited_sha256'] or
        original['artifact'] != handoff['original_sha256'] or parent['inference_artifacts'] != handoff['inference_artifacts'] or
        report['spec'] != handoff['spec'] or report['status'] != 'passed' or report['outputs'] != handoff['evaluation_output'] or
        diff['before_sha256'] != handoff['original_sha256'] or diff['after_sha256'] != handoff['inherited_sha256'] or
        record['kind'] != 'PatchProposal' or patch['parent'] != spec['base'] or patch['author'] != record['author'] or
        set(handoff['evidence_ids']) != set(record['artifacts'] + [handoff['proposal'], handoff['evaluation'], report['outputs']])):
        raise ValueError('handoff lineage mismatch')
    # Recompute the actual diff: the supplied explanation is never authoritative.
    expected = numerical_diff(artifact(root, original['artifact']), artifact(root, parent['artifact']))
    if expected != diff:
        raise ValueError('parent diff does not match checkpoint bytes')
    session = json.loads(artifact(root, spec['evidence'][0]).read_text())
    output = json.loads(artifact(root, report['outputs']).read_text())
    metric = lambda row: {k:v for k,v in row.items() if k != 'predictions'}
    if (session['candidate_sha256'] != parent['artifact'] or session['commitment']['target_sha256'] != original['artifact'] or
        session['changed_parameters'] != diff['changed_parameters'] or handoff['changed_parameters'] != diff['changed_parameters'] or
        session['commitment']['controller'] != handoff['controller'] or session['commitment']['backend'] != handoff['backend'] or
        session['selected']['hypothesis'] != handoff['hypothesis'] or session['selected']['operations'] != handoff['operations'] or
        output['spec'] != handoff['spec'] or
        handoff['development'] != metric(session['selected']['development']) or
        handoff['selection'] != metric(session['selected'].get('selection', {})) or
        handoff['previous_final'] != {k:metric(output['details'][k]) for k in ['base','candidate']}):
        raise ValueError('handoff context does not match parent evidence')
    return handoff, diff
