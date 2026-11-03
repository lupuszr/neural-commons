"""A continuation must inherit real bytes and trustworthy, reproducible context."""
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import torch
from safetensors.torch import save_file
from weight_agent import sha, write
from weight_handoff import artifact, inspect_diff, load, numerical_diff, prepare


class Handoff(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'participant'
        self.store = self.home / 'artifacts'
        self.store.mkdir(parents=True)
        def put(value):
            p = self.root / 'value.json';write(p,value);digest=sha(p)
            (self.store / digest).write_bytes(p.read_bytes());return digest
        self.put = put
        self.weights = []
        for values in [[1.,2.,3.,4.],[1.,2.5,3.,5.]]:
            p=self.root/'weights';save_file({'any.tensor':torch.tensor(values,dtype=torch.bfloat16)},p)
            digest=sha(p);(self.store/digest).write_bytes(p.read_bytes());self.weights.append(digest)
        inference={name:put({'fixture':name}) for name in ['model_config','tokenizer','tokenizer_config','special_tokens']}
        self.base=put({'artifact':self.weights[0],'inference_artifacts':inference})
        self.candidate=put({'artifact':self.weights[1],'inference_artifacts':inference})
        p=put({'parent':self.base,'author':'participant-a'})
        session=put({'schema':'nc/weight-agent-session/v1','candidate_sha256':self.weights[1],
                     'changed_parameters':2,'commitment':{'target_sha256':self.weights[0],'controller':'controller-a','backend':'codex'},
                     'selected':{'hypothesis':'improve task','operations':[], 'development':{'accuracy':0.8},'selection':{'accuracy':0.8}}})
        spec=put({'base':self.base,'candidate':self.candidate,'patch':p,'evidence':[session]})
        output=put({'spec':spec,'details':{'base':{'accuracy':0.7},'candidate':{'accuracy':0.8}}})
        self.report=put({'spec':spec,'status':'passed','outputs':output})
        self.record={'kind':'PatchProposal','author':'participant-a','artifact':spec,
                     'artifacts':self.weights+[self.base,self.candidate,p,session,spec]+list(inference.values())}
        self.proposal=put(self.record)
        self.directory=self.root/'continuation'
        def nc(home,command,*args):
            if command=='fetch':return self.record
            if command=='patch':return {'checkpoint':self.candidate}
            raise AssertionError(command)
        with patch('weight_experiment.nc',side_effect=nc):
            prepare(self.home,self.proposal,self.report,self.directory)

    def test_exact_inherited_bytes_and_sparse_diff(self):
        handoff,diff=load(self.directory,self.weights[1])
        self.assertEqual(sha(self.directory/'model/model.safetensors'),self.weights[1])
        self.assertEqual(handoff['candidate_checkpoint'],self.candidate)
        changes=inspect_diff(diff,'any.tensor',1,3)['changes']
        self.assertEqual(changes,[{'index':1,'before':2.,'after':2.5,'delta':0.5},
                                  {'index':3,'before':4.,'after':5.,'delta':1.}])
        with self.assertRaises(ValueError):inspect_diff(diff,'any.tensor',0,257)

    def test_rejects_original_model_as_continuation_base(self):
        with self.assertRaisesRegex(ValueError,'inherited checkpoint'):
            load(self.directory,self.weights[0])

    def test_rejects_forged_diff_even_if_its_hash_was_updated(self):
        p=self.directory/'parent-diff.json';d=json.loads(p.read_text());d['tensors'][0]['after'][0]=99;write(p,d)
        h=self.directory/'handoff.json';v=json.loads(h.read_text());v['diff_sha256']=sha(p);write(h,v)
        with self.assertRaisesRegex(ValueError,'checkpoint bytes'):load(self.directory,self.weights[1])

    def test_rejects_wrong_parent_link_and_forged_context(self):
        p=self.directory/'handoff.json';original=json.loads(p.read_text())
        for key,value in [('candidate_checkpoint',self.base),('controller','fake-controller'),('hypothesis','fake result')]:
            bad={**original,key:value};write(p,bad)
            with self.subTest(key=key),self.assertRaises(ValueError):load(self.directory,self.weights[1])
        write(p,original)

    def test_artifact_integrity_and_address_validation(self):
        with self.assertRaises(ValueError):artifact(self.store,'../escape')
        (self.store/self.weights[1]).write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):load(self.directory,self.weights[1])

if __name__=='__main__':unittest.main()
