#!/usr/bin/env python3
"""Reassess saved measurements under the user-requested 0.2-point policy.

This is not a new inference or DKG evaluation report. Original evidence is
verified and preserved without modification.
"""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reassess(evidence, output):
    manifest = json.loads((evidence / 'manifest.json').read_text())
    names = ['policy.json', 'spec.json', 'result.json', 'heldout-output.json']
    for name in names:
        if digest(evidence / name) != manifest['files'][name]['public_sha256']:
            raise ValueError('evidence hash mismatch: ' + name)
    old, spec, result, measured = [json.loads((evidence / n).read_text()) for n in names]
    report = result['evaluation']['evaluation']
    if (digest(evidence / 'spec.json') != result['spec'] or
            digest(evidence / 'policy.json') != spec['policy'] or
            spec['metric'] != old['metric'] or
            measured['spec'] != result['spec'] or report['spec'] != result['spec'] or
            digest(evidence / 'heldout-output.json') != report['outputs'] or
            measured['metric'] != old['metric'] or old['direction'] != 'maximize' or
            measured['base'] != report['scores']['base'] or
            measured['candidate'] != report['scores']['candidate']):
        raise ValueError('recorded measurement binding mismatch')
    policy = {**old, 'min_improvement': 0.002}
    gain = measured['candidate'] - measured['base']
    passed = (measured['candidate'] + policy['tolerance'] >= policy['threshold'] and
              gain + policy['tolerance'] >= policy['min_improvement'] and
              measured['details']['guard']['passed'])
    record = {
        'schema': 'nc/policy-reassessment/v1',
        'reason': 'User requested 0.2 percentage points after seeing the recorded result.',
        'scope': 'Local policy reassessment of existing DKG-reproduced measurements; no new inference, DKG publication or statistical significance claim.',
        'original_spec': result['spec'], 'original_report': result['evaluation']['report'],
        'original_status': report['status'], 'original_policy': old,
        'source_sha256': {n: digest(evidence / n) for n in names},
        'base_checkpoint': spec['base'], 'candidate_checkpoint': spec['candidate'],
        'revised_policy': policy, 'base': measured['base'], 'candidate': measured['candidate'],
        'improvement': gain, 'guard_passed': measured['details']['guard']['passed'],
        'status': 'passed' if passed else 'failed',
    }
    with output.open('x') as f:
        f.write(json.dumps(record, indent=2, allow_nan=False) + '\n')
    return record


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(reassess(a.evidence, a.output), indent=2))
