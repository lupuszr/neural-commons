#!/usr/bin/env python3
"""New locked task splits for an inherited AG News checkpoint received via DKG."""
import argparse
import copy
import json
import pathlib
import random
import shutil
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download
from transformers import AutoTokenizer
from prepare_agnews_experiment import DATASET, REVISION
from weight_agent import sha, write
from weight_handoff import prepare as prepare_handoff


def prepare(home, proposal, evaluation, previous, directory):
    handoff = prepare_handoff(home, proposal, evaluation, directory)
    config = json.loads((previous / 'config.json').read_text())
    tokenizer = AutoTokenizer.from_pretrained(directory / 'model', local_files_only=True)
    excluded = {row['text'] for name in ['development','selection','heldout']
                for row in json.loads((previous / (name + '.json')).read_text())['samples']}
    seen, groups, file_hashes = set(excluded), {}, {}
    for split in ['train','test']:
        path = pathlib.Path(hf_hub_download(DATASET, f'data/{split}-00000-of-00001.parquet', repo_type='dataset', revision=REVISION))
        file_hashes[split] = sha(path)
        buckets = [[] for _ in config['labels']]
        for index,row in enumerate(pq.read_table(path).to_pylist()):
            buckets[row['label']].append({'id':f'ag_news/{split}/{index}', 'text':row['text'], 'label':row['label']})
        rng = random.Random(20261108 if split == 'train' else 20261109)
        groups[split] = []
        for bucket in buckets:
            rng.shuffle(bucket)
            eligible = []
            for row in bucket:
                if row['text'] in seen:
                    continue
                seen.add(row['text'])
                if len(tokenizer.encode(config['prompt'].format(text=row['text']))) <= 220:
                    eligible.append(row)
                if len(eligible) == (192 if split == 'train' else 250):
                    break
            if len(eligible) != (192 if split == 'train' else 250):
                raise ValueError('not enough disjoint examples')
            groups[split].append(eligible)
    samples = {'development':sum((g[:64] for g in groups['train']), []),
               'selection':sum((g[64:192] for g in groups['train']), []),
               'heldout':sum(groups['test'], [])}
    for name,rows in samples.items():
        random.Random(20261110).shuffle(rows)
        write(directory / (name + '.json'), {'schema':'nc/text-classification/v1','split':name,'samples':rows})
    config['agent_objective'] += ' This is a continuation: beat the inherited model, not its original ancestor. Read the previous agent numerical diff and hypothesis, diagnose the inherited model on your new development examples, and choose additional edits. All operations start from the inherited checkpoint. Do not blindly reapply the previous patch.'
    config['selection_policy']['min_accuracy_improvement'] = 0.002
    write(directory / 'config.json', config)
    policy = json.loads((previous / 'policy.json').read_text())
    policy['min_improvement'] = 0.002
    write(directory / 'policy.json', policy)
    for name in ['guard.json','guard-config.json']:
        shutil.copyfile(previous / name, directory / name)
    source = copy.deepcopy(json.loads((previous / 'source.json').read_text()))
    source.update({'model_sha256':handoff['inherited_sha256'], 'parent_proposal':proposal,
                   'parent_checkpoint':handoff['candidate_checkpoint'], 'dataset_file_sha256':file_hashes,
                   'split_seeds':[20261108,20261109,20261110], 'development_samples':256,
                   'selection_samples':512,'heldout_samples':1000,
                   'excluded_dataset_sha256':{name:sha(previous / (name + '.json')) for name in ['development','selection','heldout']},
                   'split_method':'Exclude all exact texts from the prior experiment. Fixed per-class shuffle; prompt <=220 tokens. First 64/class train development, next 128/class selection; first 250/class remaining test final. Global exact-text deduplication; no model scores used.'})
    write(directory / 'source.json', source)
    return handoff


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['home','previous','directory']:
        p.add_argument('--'+name, type=pathlib.Path, required=True)
    for name in ['proposal','evaluation']:
        p.add_argument('--'+name, required=True)
    a=p.parse_args()
    prepare(a.home.resolve(),a.proposal,a.evaluation,a.previous.resolve(),a.directory.resolve())
