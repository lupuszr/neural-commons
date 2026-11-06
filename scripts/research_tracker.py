#!/usr/bin/env python3
"""Small client for nc's durable conversation-led research lifecycle.

The app, not the calling script, owns registration and command outcomes. A failed
registration prevents execution. Never silently fall back to untracked work.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def measurements(metrics, prefix='', role=None):
    """Normalize nested count metrics without combining datasets or split roles."""
    result = []
    if not isinstance(metrics, dict):
        return result
    if isinstance(metrics.get('n'), int) and isinstance(metrics.get('correct'), int):
        if metrics['n']:
            result.append(dict(label=prefix or 'Accuracy', split=role or split_role(prefix),
                               correct=metrics['correct'], total=metrics['n']))
        return result
    for key, value in metrics.items():
        if isinstance(value, dict):
            result.extend(measurements(value, (prefix + ' / ' + key).strip(' /'), role))
    return result


def split_role(name):
    name = name.lower()
    if 'retired' in name or 'regression' in name:
        return 'regression'
    if 'development' in name or 'train' in name:
        return 'development'
    if 'selection' in name or 'validation' in name:
        return 'selection'
    if 'final' in name or 'held' in name or 'test' in name:
        return 'final'
    return 'diagnostic'


class Tracker:
    def __init__(self, home, experiment, binary=None):
        self.home = str(Path(home).resolve())
        self.experiment = experiment
        self.binary = str(binary or ROOT / 'target/debug/nc')

    def call(self, args):
        return subprocess.run([self.binary, '--home', self.home, 'research'] + args,
                              check=True, text=True, capture_output=True)

    def event(self, kind, data, round_id=None, evidence=(), event_id=None,
              historical=False, occurred_at=None):
        event = dict(id=event_id or str(uuid.uuid4()), experiment=self.experiment,
                     kind=kind, data=data, historical=historical,
                     attachments=[p if isinstance(p, dict) else dict(label=Path(p).name, path=str(Path(p).resolve())) for p in evidence])
        if round_id is not None:
            event['round'] = round_id
        if occurred_at is not None:
            event['occurred_at'] = occurred_at
        return event

    def record(self, kind, data, **kwargs):
        event = self.event(kind, data, **kwargs)
        with tempfile.TemporaryDirectory(prefix='nc-research-') as directory:
            path = Path(directory) / 'event.json'
            path.write_text(json.dumps(event, ensure_ascii=False))
            return json.loads(self.call(['record', str(path)]).stdout)

    def run(self, round_id, definition, command, result=None, evidence=()):
        event = self.event('round', definition, round_id=round_id, evidence=evidence)
        with tempfile.TemporaryDirectory(prefix='nc-research-') as directory:
            path = Path(directory) / 'round.json'
            path.write_text(json.dumps(event, ensure_ascii=False))
            args = ['run', str(path)]
            if result:
                args += ['--result', str(Path(result).resolve())]
            args += ['--'] + [str(a) for a in command]
            # Do not swallow command/registration failures. nc persists the outcome.
            return self.call(args)

    def feedback(self, round_id, feedback_path, summary, parent_counts=None):
        feedback = json.loads(Path(feedback_path).read_text())
        metrics = measurements(feedback.get('metrics', {}))
        for metric in metrics:
            if parent_counts and metric['label'] in parent_counts:
                metric['parent_correct'] = parent_counts[metric['label']]
        for key, value in feedback.get('text_validation', {}).items():
            if key in ['perplexity_ratio_to_a', 'argmax_agreement_to_a']:
                metrics.append(dict(label='Text validation / ' + key, split='selection', value=value))
        data = dict(status='completed', summary=summary, measurements=metrics)
        for key in ['changed_tensors', 'changed_values', 'replacement_sha256', 'parent_sha256']:
            if key in feedback:
                data[key] = feedback[key]
        return self.record('result', data, round_id=round_id, evidence=[feedback_path])
